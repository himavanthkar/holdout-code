"""Honesty rule: no prompt may contain hidden (plus) inputs, and the improver/red team never see audit/unseen text."""
import pytest

from holdout.genome import gen0
from holdout.grader import _dataset, visible_check
from holdout.improver import build_prompt
from holdout.redteam import llm_cheat  # noqa: F401  (imported so a seal regression there breaks collection)
from holdout.seal import SealBroken, check
from holdout.tasks import pools, public_task
from holdout.team import system_prompt, task_message


def _plus_reprs(ds, tid, k=15):
    t = _dataset(ds)[tid]
    out = []
    for args in t["plus_input"][:k]:
        r = repr(args)[1:-1]
        if len(r) > 12:
            out.append(r)
    return out


def _fake_results(items):
    res = []
    for ds, tid in items:
        entry = _dataset(ds)[tid]["entry_point"]
        vis = visible_check(tid, f"def {entry}(*a, **k):\n    return None\n", ds)
        res.append({"task": tid, "visible_pass": False, "visible_n_pass": vis["n_pass"], "visible_n": vis["n"],
                    "visible_fails": vis["fails"], "trace": [{"role": "solver"}], "code": "def f(): pass", "calls": 1})
    return res


def test_team_prompts_have_no_plus_inputs():
    g = gen0()
    for ds, tid in pools()["train"][:10] + pools()["unseen"][:5]:
        text = system_prompt(g, "solver") + task_message(public_task(ds, tid), g)
        for r in _plus_reprs(ds, tid):
            base = [repr(a)[1:-1] for a in _dataset(ds)[tid]["base_input"]]
            if any(r in b for b in base):
                continue  # identical to a visible input: not secret
            assert r not in text, (tid, r[:60])


def test_improver_prompt_sealed():
    train = pools()["train"][:8]
    prompt = build_prompt(gen0(), _fake_results(train), [], 2)
    for ds, tid in train:
        base = [repr(a)[1:-1] for a in _dataset(ds)[tid]["base_input"]]
        for r in _plus_reprs(ds, tid):
            if not any(r in b for b in base):
                assert r not in prompt
    for ds, tid in pools()["audit"] + pools()["unseen"]:
        assert _dataset(ds)[tid]["prompt"].strip()[:120] not in prompt


def test_seal_trips_on_audit_text():
    ds, tid = pools()["audit"][0]
    with pytest.raises(SealBroken):
        check("look at this task: " + _dataset(ds)[tid]["prompt"])


def test_pools_disjoint():
    P = pools()
    ids = [t for v in P.values() for _, t in v]
    assert len(ids) == len(set(ids))
