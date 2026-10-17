"""EvalPlus tasks and the three sealed pools.

The team sees a task's prompt plus its VISIBLE tests (EvalPlus base inputs with canonical outputs, as asserts).
Hidden tests (plus inputs) never leave holdout/grader.py. Pools are disjoint and fixed by SEED:
  train  = 30 MBPP+ (the improver sees visible results and traces from here only)
  audit  = 30 other MBPP+ (hidden-test losses, reachable only through the Ladder gate)
  smoke  = 20 other MBPP+ (gen-0 headroom check)
  unseen = HumanEval+ (a different benchmark, opened once at the very end)
"""
from __future__ import annotations

import random
from functools import lru_cache

from .config import N_AUDIT, N_SMOKE, N_TRAIN, N_UNSEEN, SEED


@lru_cache(maxsize=2)
def _dataset(name: str = "humaneval"):
    if name == "mbpp":
        from evalplus.data import get_mbpp_plus
        return get_mbpp_plus()
    from evalplus.data import get_human_eval_plus
    return get_human_eval_plus()


@lru_cache(maxsize=4)
def pools(seed: int = SEED) -> dict[str, list[tuple[str, str]]]:
    mbpp = sorted(_dataset("mbpp"))
    random.Random(seed).shuffle(mbpp)
    he = sorted(_dataset("humaneval"))
    random.Random(seed).shuffle(he)
    a, b, c = N_TRAIN, N_TRAIN + N_AUDIT, N_TRAIN + N_AUDIT + N_SMOKE
    return {
        "train": [("mbpp", t) for t in mbpp[:a]],
        "audit": [("mbpp", t) for t in mbpp[a:b]],
        "smoke": [("mbpp", t) for t in mbpp[b:c]],
        "unseen": [("humaneval", t) for t in he[:N_UNSEEN]],
    }


def _short(x, limit: int = 300) -> str:
    s = repr(x)
    return s if len(s) <= limit else s[:limit] + "...<truncated>"


def visible_asserts(dataset: str, task_id: str) -> list[str]:
    """Base inputs + canonical outputs rendered as asserts (what a developer's small test suite looks like)."""
    from .grader import canonical_outputs

    t = _dataset(dataset)[task_id]
    exp = canonical_outputs(task_id, dataset)[: len(t["base_input"])]
    out = []
    for args, (kind, val) in zip(t["base_input"], exp):
        call = f"{t['entry_point']}({', '.join(_short(a) for a in args)})"
        out.append(f"assert {call} == {_short(val)}" if kind == "ok" else f"# {call} raises {val}")
    return out


def public_task(dataset: str, task_id: str) -> dict:
    t = _dataset(dataset)[task_id]
    return {"id": task_id, "dataset": dataset, "prompt": t["prompt"], "entry_point": t["entry_point"],
            "visible": visible_asserts(dataset, task_id)}
