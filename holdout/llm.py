"""OpenAI-SDK client per role: backoff on 429/5xx, JSON extraction, response cache, per-call logging."""
from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
from dataclasses import dataclass, field

import openai
from openai import OpenAI

from .config import CONCURRENCY, PRICES, RUNS, SPEND_CAP_USD, Role

LOG_DIR = RUNS / "logs"
CACHE_DIR = RUNS / "cache"
_clients: dict[tuple[str, str], OpenAI] = {}
_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}  # identical concurrent requests are computed once, then cached
_inflight = threading.BoundedSemaphore(CONCURRENCY)  # the Crusoe key is shared with another session: cap at 6
LEDGER: dict[str, dict] = {}  # model -> {calls, cache_hits, tokens_in, tokens_out, cached_in, usd}


class SpendCapExceeded(RuntimeError):
    """Estimated spend passed SPEND_CAP_USD: stop and tell the human."""


def _account(model: str, reply: "Reply") -> None:
    pin, pout = PRICES.get(model, (0.5, 2.0))
    with _lock:
        row = LEDGER.setdefault(model, {"calls": 0, "cache_hits": 0, "tokens_in": 0, "tokens_out": 0,
                                        "cached_in": 0, "usd": 0.0})
        if reply.cached:
            row["cache_hits"] += 1
            return
        row["calls"] += 1
        row["tokens_in"] += reply.tokens_in
        row["tokens_out"] += reply.tokens_out
        row["cached_in"] += reply.cached_in
        row["usd"] += (reply.tokens_in * pin + reply.tokens_out * pout) / 1e6
        total = sum(r["usd"] for r in LEDGER.values())
    if total > SPEND_CAP_USD:
        raise SpendCapExceeded(f"estimated spend ${total:.2f} passed the ${SPEND_CAP_USD:.0f} cap")


def spend_summary() -> dict:
    with _lock:
        rows = {m: dict(r) for m, r in LEDGER.items()}
    tot = {k: sum(r[k] for r in rows.values()) for k in ("calls", "cache_hits", "tokens_in", "tokens_out", "cached_in", "usd")}
    return {"by_model": rows, "total": tot}


class BudgetExceeded(RuntimeError):
    """MAX_LLM_CALLS_PER_TASK or the wall-clock cap was hit."""


@dataclass
class Tracker:
    """Per-task accounting: timeline, call budget, wall-clock budget."""

    task_id: str = "adhoc"
    max_calls: int = 14
    wall_clock_s: float = 180.0
    started: float = field(default_factory=time.time)
    calls: int = 0
    tokens: int = 0
    timeline: list = field(default_factory=list)
    on_event: object = None  # optional callback(dict) for the live demo

    def check(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"LLM call budget hit ({self.max_calls})")
        if time.time() - self.started > self.wall_clock_s:
            raise BudgetExceeded(f"wall-clock cap hit ({self.wall_clock_s:.0f}s)")

    def record(self, step: str, agent: str, model: str, duration_s: float, tokens: int, cached: bool = False) -> None:
        self.calls += 1
        self.tokens += tokens
        self.timeline.append(
            {"step": step, "agent": agent, "model": model, "duration_s": round(duration_s, 2), "tokens": tokens, "cached": cached}
        )

    def elapsed(self) -> float:
        return time.time() - self.started


@dataclass
class Reply:
    text: str
    tokens_in: int
    tokens_out: int
    latency_s: float
    cached: bool = False  # served from our disk cache
    cached_in: int = 0  # prompt tokens Crusoe reported as KV-cache hits (prompt_tokens_details.cached_tokens)

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


def client_for(role: Role) -> OpenAI:
    key = (role.base_url, role.api_key)
    with _lock:
        if key not in _clients:
            if not role.api_key:
                raise RuntimeError(f"No API key for role '{role.name}'. Set CRUSOE_API_KEY in .env")
            _clients[key] = OpenAI(base_url=role.base_url, api_key=role.api_key, max_retries=0, timeout=90)
        return _clients[key]


def extra_body_for(model: str, thinking: bool | None) -> dict:
    """Pin thinking explicitly per family (see NOTES.md)."""
    m = model.lower()
    if thinking is None:
        return {}
    if "nemotron" in m or "qwen" in m:
        return {"chat_template_kwargs": {"enable_thinking": thinking}}
    if "deepseek" in m:
        return {"chat_template_kwargs": {"thinking": thinking}}
    return {}


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def _log(row: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with _lock, open(LOG_DIR / "llm_calls.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")


def chat(
    role: Role,
    messages: list[dict],
    *,
    tracker: Tracker | None = None,
    step: str = "",
    max_tokens: int = 4096,
    thinking: bool | None = False,
    use_cache: bool = False,
    temperature: float | None = None,
    json_mode: bool = False,
) -> Reply:
    if tracker:
        tracker.check()
    temp = role.temperature if temperature is None else temperature
    extra = extra_body_for(role.model, thinking)
    req = {"model": role.model, "base_url": role.base_url, "messages": messages, "temperature": temp,
           "max_tokens": max_tokens, "extra": extra}
    if json_mode:
        req["json_mode"] = True
    h = _hash(req)
    cache_file = CACHE_DIR / f"{h}.json"
    with _lock:
        klock = _key_locks.setdefault(h, threading.Lock())
    with klock:
        return _chat_locked(role, messages, tracker, step, max_tokens, use_cache, temp, extra, json_mode, h, cache_file)


def _chat_locked(role, messages, tracker, step, max_tokens, use_cache, temp, extra, json_mode, h, cache_file) -> Reply:
    if use_cache and cache_file.exists():
        d = json.loads(cache_file.read_text())
        reply = Reply(d["text"], d["tokens_in"], d["tokens_out"], 0.0, cached=True, cached_in=d.get("cached_in", 0))
    else:
        reply = _call_with_backoff(role, messages, temp, max_tokens, extra, json_mode=json_mode)
        if use_cache and reply.text:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"text": reply.text, "tokens_in": reply.tokens_in, "tokens_out": reply.tokens_out,
                                              "cached_in": reply.cached_in, "latency_s": reply.latency_s}))
    _account(role.model, reply)

    if tracker:
        tracker.record(step or role.name, role.name, role.model, reply.latency_s, reply.tokens, reply.cached)
    _log({"ts": time.time(), "task": tracker.task_id if tracker else None, "step": step, "role": role.name,
          "model": role.model, "prompt_hash": h[:16], "tokens_in": reply.tokens_in, "tokens_out": reply.tokens_out,
          "latency_s": round(reply.latency_s, 2), "cached": reply.cached, "cached_in": reply.cached_in})
    return reply


def _call_with_backoff(role: Role, messages, temp, max_tokens, extra, max_tries: int = 8, json_mode: bool = False) -> Reply:
    client = client_for(role)
    last_err = None
    for attempt in range(max_tries):
        t0 = time.time()
        try:
            with _inflight:
                t0 = time.time()
                resp = client.chat.completions.create(
                    model=role.model, messages=messages, temperature=temp, max_tokens=max_tokens,
                    **({"extra_body": extra} if extra else {}),
                    **({"response_format": {"type": "json_object"}} if json_mode else {}),
                )
            msg = resp.choices[0].message
            text = msg.content or ""
            if not text.strip():
                # reasoning model starved or put the answer in the reasoning field
                d = msg.model_dump()
                text = d.get("reasoning_content") or d.get("reasoning") or ""
            u = resp.usage
            details = getattr(u, "prompt_tokens_details", None)
            cached_in = (getattr(details, "cached_tokens", 0) or 0) if details else 0
            return Reply(text, getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0,
                         time.time() - t0, cached_in=cached_in)
        except openai.BadRequestError as e:
            if extra or json_mode:  # some deployments reject chat_template_kwargs / response_format; retry plain
                extra, json_mode = {}, False
                last_err = e
                continue
            raise
        except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError, openai.APITimeoutError) as e:
            last_err = e
            if attempt == max_tries - 1:
                break
            time.sleep(min(30.0, 1.0 * 2**attempt) + random.uniform(0, 0.5))
    raise RuntimeError(f"{role.name} ({role.model}) failed after retries: {last_err}")


# ---------------------------------------------------------------- JSON extraction

_FENCE = re.compile(r"```([a-zA-Z0-9_+-]*)\s*\n(.*?)```", re.S)


def code_fences(text: str, lang: str | None = None) -> list[str]:
    out = []
    for tag, body in _FENCE.findall(text or ""):
        if lang is None or tag.lower() in (lang, f"{lang}3", "py" if lang == "python" else lang):
            out.append(body)
    return out


def _balanced_objects(text: str):
    """Yield every top-level {...} substring, string-aware."""
    depth, start, in_str, esc = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start : i + 1]


def extract_json(text: str) -> dict | None:
    """Tolerates code fences, prose around the object, and a trailing comma or two."""
    if not text:
        return None
    candidates = [text.strip()]
    candidates += [b for b in code_fences(text) if b.strip().startswith("{")]
    candidates += sorted(_balanced_objects(text), key=len, reverse=True)
    for c in candidates:
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", c)  # invalid escapes like \( or \_ from code snippets
        for attempt in (c, re.sub(r",\s*([}\]])", r"\1", c), fixed, re.sub(r",\s*([}\]])", r"\1", fixed)):
            try:
                obj = json.loads(attempt, strict=False)
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError):
                pass
    return None
