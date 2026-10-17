"""The genome: everything the team may rewrite about itself (prompts, playbook, tools, structure, budget).

Diffs are JSON op lists; apply_ops never mutates its input and rejects ops that break the schema limits.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import yaml

from .config import GENOMES, WORKER_CHOICES, WORKER_MODEL

MAX_RULES = 10
MAX_PLAYBOOK_TOKENS = 800  # approximated as chars / 4
ROLES = ("solver", "repairer", "reviewer")
TOOLS = ("run_visible_tests", "edge_case_enumerator")
OPS = ("add_rule", "edit_rule", "delete_rule", "edit_prompt", "toggle_tool", "change_model", "toggle_role", "set_budget")


def gen0() -> dict:
    return {
        "roles": {
            "solver": {"model": WORKER_MODEL, "enabled": True,
                       "prompt": "You are the solver. Write a correct, complete Python function for the task."},
            "repairer": {"model": WORKER_MODEL, "enabled": True, "max_repairs": 1,
                         "prompt": "You are the repairer. The code below fails some visible tests. Fix the bug."},
            "reviewer": {"model": WORKER_MODEL, "enabled": False,
                         "prompt": "You are the reviewer. Check the code for edge cases the tests may not cover "
                                   "and return an improved version."},
        },
        "playbook": [],
        "tools": {"run_visible_tests": True, "edge_case_enumerator": False},
        "budget": {"max_calls_per_task": 3},
    }


def canonical(g: dict) -> str:
    return json.dumps(g, sort_keys=True, separators=(",", ":"))


def genome_hash(g: dict) -> str:
    return hashlib.sha256(canonical(g).encode()).hexdigest()[:12]


def playbook_tokens(rules: list[str]) -> int:
    return sum(len(r) for r in rules) // 4


class OpError(ValueError):
    pass


def _apply_one(g: dict, op: dict) -> None:
    kind = op.get("op")
    pb = g["playbook"]
    if kind == "add_rule":
        rule = str(op.get("rule", "")).strip()
        if not rule:
            raise OpError("empty rule")
        if len(pb) >= MAX_RULES:
            raise OpError("playbook full (10 rules)")
        pb.append(rule)
    elif kind in ("edit_rule", "delete_rule"):
        i = op.get("index")
        if not isinstance(i, int) or not 0 <= i < len(pb):
            raise OpError(f"bad rule index {i}")
        if kind == "edit_rule":
            rule = str(op.get("rule", "")).strip()
            if not rule:
                raise OpError("empty rule")
            pb[i] = rule
        else:
            pb.pop(i)
    elif kind == "edit_prompt":
        r, p = op.get("role"), str(op.get("prompt", "")).strip()
        if r not in ROLES or not p:
            raise OpError(f"bad edit_prompt {r}")
        g["roles"][r]["prompt"] = p[:1200]
    elif kind == "toggle_tool":
        t = op.get("tool")
        if t not in TOOLS:
            raise OpError(f"unknown tool {t}")
        g["tools"][t] = bool(op.get("value", not g["tools"][t]))
    elif kind == "change_model":
        r, m = op.get("role"), op.get("model")
        if r not in ROLES or m not in WORKER_CHOICES:
            raise OpError(f"bad change_model {r} {m}")
        g["roles"][r]["model"] = m
    elif kind == "toggle_role":
        r = op.get("role")
        if r not in ("repairer", "reviewer"):
            raise OpError(f"cannot toggle {r}")
        g["roles"][r]["enabled"] = bool(op.get("enabled", not g["roles"][r]["enabled"]))
    elif kind == "set_budget":
        if "max_calls_per_task" in op:
            g["budget"]["max_calls_per_task"] = max(1, min(4, int(op["max_calls_per_task"])))
        if "max_repairs" in op:
            g["roles"]["repairer"]["max_repairs"] = max(0, min(2, int(op["max_repairs"])))
    else:
        raise OpError(f"unknown op {kind}")
    if playbook_tokens(pb) > MAX_PLAYBOOK_TOKENS:
        raise OpError("playbook over 800 tokens")


def apply_ops(g: dict, ops: list[dict]) -> tuple[dict, list[dict], list[str]]:
    """-> (new genome, applied ops, errors). Bad ops are skipped, good ones kept."""
    new = copy.deepcopy(g)
    applied, errors = [], []
    for op in ops or []:
        trial = copy.deepcopy(new)
        try:
            _apply_one(trial, op)
            new = trial
            applied.append(op)
        except (OpError, TypeError, ValueError, KeyError) as e:
            errors.append(f"{op.get('op')}: {e}")
    return new, applied, errors


def describe_ops(ops: list[dict]) -> str:
    parts = []
    for op in ops:
        k = op.get("op")
        if k in ("add_rule", "edit_rule"):
            parts.append(f'{k}: "{str(op.get("rule", ""))[:90]}"')
        elif k == "edit_prompt":
            parts.append(f'edit_prompt[{op.get("role")}]: "{str(op.get("prompt", ""))[:70]}"')
        else:
            parts.append(json.dumps({x: y for x, y in op.items()}))
    return "; ".join(parts)


def save(g: dict, arm: str, gen: int, root: Path = GENOMES) -> Path:
    d = root / arm
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"gen_{gen}.yaml"
    p.write_text(f"# HOLDOUT genome, arm={arm}, generation={gen}, hash={genome_hash(g)}\n"
                 + yaml.safe_dump(g, sort_keys=False, width=110, allow_unicode=True))
    return p


def load(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text())
