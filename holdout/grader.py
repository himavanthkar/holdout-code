"""Hidden ground truth: differential testing vs canonical_solution on base_input + plus_input.

Never imported from pod/. Candidate and canonical each run in a stripped subprocess with a timeout; inputs are
deep-copied before every call; floats compared with atol; an exception is a mismatch unless canonical also raised.
"""
from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .config import RUNS

from .tasks import _dataset

CANON_DIR = RUNS / "cache" / "canonical"

_RUNNER = r'''
import copy, pickle, sys, json, math
sys.setrecursionlimit(10000)
src = open("candidate.py").read()
ns = {"__name__": "candidate"}
try:
    exec(compile(src, "candidate.py", "exec"), ns)
    fn = ns[sys.argv[1]]
except Exception as e:
    print(json.dumps({"load_error": repr(e)[:300]})); sys.exit(0)
inputs = pickle.load(open("inputs.pkl", "rb"))
mode = sys.argv[2]
outs = []
fails = []
if mode in ("compare", "compare_all"):
    expected = pickle.load(open("expected.pkl", "rb"))
    atol = float(sys.argv[3])

import numpy as np
DATASET = sys.argv[4] if len(sys.argv) > 4 else "humaneval"
ENTRY = sys.argv[1]
# mirrors evalplus.eval.unsafe_execute + _special_oracle (evalplus 0.x) so our hidden verdicts match the official grader
SET_EQ = {"similar_elements", "find_char_long", "common_in_nested_lists", "extract_singly", "larg_nnum",
          "intersection_array", "find_dissimilar", "Diff"}
NOT_NONE = {"check_str", "text_match_three", "text_starta_endb"}

def is_floats(x):
    if isinstance(x, float):
        return True
    if isinstance(x, (list, tuple)) and x:
        return all(isinstance(i, float) for i in x)
    if isinstance(x, np.ndarray):
        return x.dtype == np.float64 or x.dtype == np.float32
    return False

def _surface_Area(base_edge, height):
    slant = math.sqrt((base_edge / 2) ** 2 + height ** 2)
    return round(base_edge ** 2 + 4 * (base_edge * slant) / 2)

def _digit_distance_nums(a, b):
    x, y = str(a), str(b)
    m = max(len(x), len(y))
    return sum(abs(int(p) - int(q)) for p, q in zip(x.zfill(m), y.zfill(m)))

def _poly(xs, x):
    return sum(c * math.pow(x, i) for i, c in enumerate(xs))

def matches(inp, out, exp, atol):
    try:
        exact = out == exp
        if isinstance(exact, np.ndarray):
            exact = bool(exact.all())
        if DATASET == "mbpp":
            if ENTRY == "are_equivalent":
                exact = True
            elif ENTRY == "sum_div":
                exact = exact or out == 0
            elif ENTRY == "surface_Area":
                exact = exact or abs(out - _surface_Area(*inp)) <= atol
            elif ENTRY == "digit_distance_nums":
                exact = exact or out == _digit_distance_nums(*inp)
            elif ENTRY in SET_EQ:
                exact = set(out) == set(exp)
            elif ENTRY in NOT_NONE:
                exact = (out == exp) if isinstance(out, bool) else (exp == (out is not None))
        if DATASET == "humaneval" and ENTRY == "find_zero":
            return abs(_poly(*inp, out)) <= atol
        if atol == 0 and is_floats(exp):
            atol = 1e-6
        if not exact and atol != 0:
            if type(out) != type(exp):
                return False
            if isinstance(exp, (list, tuple)) and len(out) != len(exp):
                return False
            return bool(np.allclose(out, exp, rtol=1e-07, atol=atol))
        return bool(exact)
    except BaseException:
        return False

for i, args in enumerate(inputs):
    try:
        out = ("ok", fn(*copy.deepcopy(args)))
    except BaseException as e:
        out = ("exc", type(e).__name__)
    if mode == "record":
        if out[0] == "ok" and DATASET == "mbpp" and ENTRY in NOT_NONE and not isinstance(out[1], bool):
            out = ("ok", out[1] is not None)  # evalplus stores not-None oracles as bools
        try:
            pickle.dumps(out)
        except Exception:
            out = ("ok", repr(out[1]))
        outs.append(out)
    else:
        exp = expected[i]
        ok = (exp[0] == "exc" and out[0] == "exc") or (exp[0] == "ok" and out[0] == "ok" and matches(args, out[1], exp[1], atol))
        if not ok:
            row = {"pass": False, "index": i, "input": repr(args)[:200], "got": repr(out)[:200], "expected": repr(exp)[:200]}
            if mode == "compare_all":
                fails.append(row)
                continue
            print(json.dumps(row))
            sys.exit(0)
if mode == "compare_all":
    print(json.dumps({"pass": not fails, "n": len(inputs), "fails": fails}))
elif mode == "record":
    pickle.dump(outs, open("expected.pkl", "wb"))
    print(json.dumps({"recorded": len(outs)}))
else:
    print(json.dumps({"pass": True, "n": len(inputs)}))
'''


def _run(code: str, entry: str, inputs: list, mode: str, expected: list | None = None, atol: float = 0,
         timeout: float = 60, dataset: str = "humaneval") -> tuple[dict, list | None]:
    with tempfile.TemporaryDirectory(prefix="pod_hidden_") as d:
        p = Path(d)
        (p / "candidate.py").write_text(code)
        (p / "runner.py").write_text(_RUNNER)
        with open(p / "inputs.pkl", "wb") as f:
            pickle.dump(inputs, f)
        if expected is not None:
            with open(p / "expected.pkl", "wb") as f:
                pickle.dump(expected, f)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": d, "PYTHONHASHSEED": "0"}
        try:
            r = subprocess.run([sys.executable, "runner.py", entry, mode, str(atol), dataset], cwd=p, env=env,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"pass": False, "reason": f"timeout {timeout}s"}, None
        line = (r.stdout.strip().splitlines() or ["{}"])[-1]
        try:
            res = json.loads(line)
        except json.JSONDecodeError:
            res = {"pass": False, "reason": (r.stderr or r.stdout)[-300:]}
        rec = None
        if mode == "record" and (p / "expected.pkl").exists():
            rec = pickle.loads((p / "expected.pkl").read_bytes())
        return res, rec


def canonical_outputs(task_id: str, dataset: str = "humaneval") -> list:
    CANON_DIR.mkdir(parents=True, exist_ok=True)
    f = CANON_DIR / (task_id.replace("/", "_") + ".pkl")
    if f.exists():
        try:
            return pickle.loads(f.read_bytes())
        except (EOFError, pickle.UnpicklingError):
            pass  # corrupt cache: recompute
    t = _dataset(dataset)[task_id]
    inputs = t["base_input"] + t["plus_input"]
    res, rec = _run(t["prompt"] + t["canonical_solution"], t["entry_point"], inputs, "record", timeout=300,
                    dataset=dataset)
    if rec is None:
        raise RuntimeError(f"canonical failed for {task_id}: {res}")
    tmp = f.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(pickle.dumps(rec))
    os.replace(tmp, f)  # atomic: concurrent conditions never read a half-written cache file
    return rec


def hidden_pass(task_id: str, code: str, dataset: str = "humaneval", timeout: float = 60) -> dict:
    """{'pass': bool, ...mismatch details}"""
    if not code or not code.strip():
        return {"pass": False, "reason": "no code"}
    t = _dataset(dataset)[task_id]
    expected = canonical_outputs(task_id, dataset)
    res, _ = _run(code, t["entry_point"], t["base_input"] + t["plus_input"], "compare", expected,
                  float(t.get("atol") or 0), timeout, dataset)
    if "load_error" in res:
        return {"pass": False, "reason": res["load_error"]}
    res.setdefault("pass", False)
    return res


def visible_check(task_id: str, code: str, dataset: str = "mbpp", timeout: float = 15) -> dict:
    """Run code on the VISIBLE (base) inputs only. {'pass', 'n', 'n_pass', 'fails': [{index,input,got,expected}]}"""
    t = _dataset(dataset)[task_id]
    n = len(t["base_input"])
    if not code or not code.strip():
        return {"pass": False, "n": n, "n_pass": 0, "fails": [], "reason": "no code"}
    expected = canonical_outputs(task_id, dataset)[:n]
    res, _ = _run(code, t["entry_point"], t["base_input"], "compare_all", expected, float(t.get("atol") or 0),
                  timeout, dataset)
    if "load_error" in res or "fails" not in res:
        reason = res.get("load_error") or res.get("reason", "error")
        return {"pass": False, "n": n, "n_pass": 0, "fails": [{"index": -1, "input": "<load>", "got": reason,
                                                                "expected": ""}], "reason": reason}
    res["n_pass"] = n - len(res["fails"])
    return res
