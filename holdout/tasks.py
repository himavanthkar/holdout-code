"""Benchmark tasks. Agents see ONLY `goal` (prompt = signature + docstring); never solutions or inputs."""
from __future__ import annotations

import random
import re
from functools import lru_cache

from .config import EVAL_N, EVAL_SEED


@lru_cache(maxsize=2)
def _dataset(name: str = "humaneval"):
    if name == "mbpp":
        from evalplus.data import get_mbpp_plus
        return get_mbpp_plus()
    from evalplus.data import get_human_eval_plus
    return get_human_eval_plus()


def signature_of(prompt: str, entry_point: str) -> str:
    m = re.search(rf"^def {re.escape(entry_point)}\(.*?\).*?:\s*$", prompt, re.M | re.S)
    return m.group(0).strip() if m else f"def {entry_point}(...)"


def public_task(task_id: str, dataset: str = "humaneval") -> dict:
    t = _dataset(dataset)[task_id]
    return {"id": task_id, "goal": t["prompt"], "entry_point": t["entry_point"],
            "signature": signature_of(t["prompt"], t["entry_point"]), "dataset": dataset}


def sample_tasks(n: int = EVAL_N, seed: int = EVAL_SEED, dataset: str = "humaneval") -> list[dict]:
    ids = sorted(_dataset(dataset))
    random.Random(seed).shuffle(ids)  # prefix-stable: the first 30 of N=100 are the N=30 sample
    return [public_task(i, dataset) for i in ids[:n]]
