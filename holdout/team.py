"""Run a genome (the coding team) on one task: solver -> visible tests -> repairer -> optional reviewer.

Prompt layout is MemoryAlloy-friendly: the system message [base + role prompt + playbook + tool schema] is
byte-identical for every task under one genome; all task-specific text comes after it, in the user message.
Hidden (plus) tests are computed here by the harness for scoring and never enter any prompt.
"""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from . import config as C
from .genome import genome_hash
from .grader import hidden_pass, visible_check
from .llm import chat, code_fences
from .tasks import public_task

TEAM_CACHE = C.RUNS / "cache" / "team"
_cache_lock = threading.Lock()

BASE = ("You are one member of a small Python coding team that solves programming tasks. "
        "Always answer with the complete function in a single ```python code block, including imports. "
        "No explanation outside the code block.")

TOOL_SCHEMA = {
    "run_visible_tests": "run_visible_tests(code) -> pass/fail for each visible assert (input, got, expected)",
    "edge_case_enumerator": "edge_case_enumerator(task) -> list of edge-case input categories to consider",
}

EDGE_CASES = ("empty inputs (empty list/string/dict, 0)", "a single element", "negative numbers and zero",
              "duplicates and ties", "very large or very small values", "unsorted input / reversed input",
              "mixed or unusual types the docstring allows", "boundary indices (first, last, out of range)")


def system_prompt(genome: dict, role: str) -> str:
    """Byte-identical prefix for every call of `role` under this genome."""
    r = genome["roles"][role]
    tools = [f"- {TOOL_SCHEMA[t]}" for t, on in genome["tools"].items() if on]
    rules = "\n".join(f"{i + 1}. {rule}" for i, rule in enumerate(genome["playbook"])) or "(none yet)"
    return (f"{BASE}\n\nYour role: {r['prompt']}\n\nTeam playbook (follow these rules):\n{rules}\n\n"
            f"Tools the harness runs for you:\n" + ("\n".join(tools) or "- (none)"))


def _clean(v: str) -> str:
    m = re.match(r"^\('ok', (.*)\)$", v or "", re.S)
    if m:
        return m.group(1)
    m = re.match(r"^\('exc', '(.*)'\)$", v or "", re.S)
    return f"raised {m.group(1)}" if m else (v or "")


def format_fails(entry: str, fails: list[dict]) -> str:
    lines = []
    for f in fails[:6]:
        inp = f.get("input", "")
        call = f"{entry}({inp[1:-1]})" if inp.startswith("[") and inp.endswith("]") else f"{entry}(*{inp})"
        lines.append(f"- {call}  got: {_clean(f.get('got', ''))}  expected: {_clean(f.get('expected', ''))}")
    return "\n".join(lines)


def extract_code(text: str) -> str:
    fences = code_fences(text, "python") or code_fences(text)
    return (fences[-1] if fences else text or "").strip() + "\n"


def task_message(task: dict, genome: dict) -> str:
    msg = f"Task:\n{task['prompt'].strip()}\n\nVisible tests:\n" + "\n".join(task["visible"])
    if genome["tools"].get("edge_case_enumerator") and not genome["roles"]["reviewer"]["enabled"]:
        msg += "\n\nedge_case_enumerator output:\n" + "\n".join(f"- {e}" for e in EDGE_CASES)
    return msg + f"\n\nWrite the complete function `{task['entry_point']}`."


def _call(genome, role, user, acc, step):
    r = genome["roles"][role]
    rep = chat(C.role(role, r["model"], C.T_WORKER),
               [{"role": "system", "content": system_prompt(genome, role)}, {"role": "user", "content": user}],
               step=step, max_tokens=1500, thinking=False, use_cache=True)
    acc["calls"] += 1
    acc["tokens_in"] += rep.tokens_in
    acc["tokens_out"] += rep.tokens_out
    acc["cached_in"] += rep.cached_in
    return extract_code(rep.text)


def run_task(genome: dict, dataset: str, task_id: str) -> dict:
    gh = genome_hash(genome)
    cf = TEAM_CACHE / gh / f"{dataset}_{task_id.replace('/', '_')}.json"
    if cf.exists():
        return json.loads(cf.read_text())
    task = public_task(dataset, task_id)
    entry = task["entry_point"]
    budget = genome["budget"]["max_calls_per_task"]
    acc = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cached_in": 0}
    trace = []
    run_tests = genome["tools"]["run_visible_tests"]

    code = _call(genome, "solver", task_message(task, genome), acc, "solver")
    vis = visible_check(task_id, code, dataset)
    trace.append({"role": "solver", "visible": f"{vis['n_pass']}/{vis['n']}"})

    rp = genome["roles"]["repairer"]
    repairs = 0
    while (run_tests and rp["enabled"] and not vis["pass"] and repairs < rp.get("max_repairs", 1)
           and acc["calls"] < budget):
        user = (f"Task:\n{task['prompt'].strip()}\n\nVisible tests:\n" + "\n".join(task["visible"])
                + f"\n\nCurrent code:\n```python\n{code}```\n\nrun_visible_tests: {vis['n_pass']}/{vis['n']} pass. "
                f"Failing visible tests:\n{format_fails(entry, vis['fails'])}\n\n"
                f"Return the complete fixed function `{entry}`.")
        code = _call(genome, "repairer", user, acc, "repairer")
        vis = visible_check(task_id, code, dataset)
        repairs += 1
        trace.append({"role": "repairer", "visible": f"{vis['n_pass']}/{vis['n']}"})

    rv = genome["roles"]["reviewer"]
    if rv["enabled"] and acc["calls"] < budget:
        user = f"Task:\n{task['prompt'].strip()}\n\nVisible tests:\n" + "\n".join(task["visible"])
        if genome["tools"].get("edge_case_enumerator"):
            user += "\n\nedge_case_enumerator output:\n" + "\n".join(f"- {e}" for e in EDGE_CASES)
        user += f"\n\nCode to review:\n```python\n{code}```\n\nReturn the complete improved function `{entry}`."
        new = _call(genome, "reviewer", user, acc, "reviewer")
        nvis = visible_check(task_id, new, dataset)
        keep = (not run_tests) or nvis["n_pass"] >= vis["n_pass"]  # a developer reverts a review that breaks tests
        if keep:
            code, vis = new, nvis
        trace.append({"role": "reviewer", "visible": f"{nvis['n_pass']}/{nvis['n']}", "kept": keep})

    hid = hidden_pass(task_id, code, dataset)  # harness only: never shown to any agent
    out = {"task": task_id, "dataset": dataset, "genome": gh, "code": code,
           "visible_pass": bool(vis["pass"]), "visible_n_pass": vis["n_pass"], "visible_n": vis["n"],
           "visible_fails": vis["fails"][:4], "hidden_pass": bool(hid.get("pass")), **acc, "trace": trace}
    cf.parent.mkdir(parents=True, exist_ok=True)
    with _cache_lock:
        cf.write_text(json.dumps(out))
    return out


def evaluate(genome: dict, items: list[tuple[str, str]], workers: int = 12) -> list[dict]:
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda it: run_task(genome, it[0], it[1]), items))


def score(results: list[dict]) -> dict:
    n = len(results) or 1
    return {"n": len(results), "visible": sum(r["visible_pass"] for r in results) / n,
            "hidden": sum(r["hidden_pass"] for r in results) / n,
            "losses": [0 if r["hidden_pass"] else 1 for r in results],
            "calls": sum(r["calls"] for r in results), "tokens": sum(r["tokens_in"] + r["tokens_out"] for r in results)}
