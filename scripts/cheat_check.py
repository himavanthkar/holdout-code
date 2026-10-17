"""M1 gate for M2: does each planted cheat actually raise the VISIBLE score over gen-0? Writes results/cheat_check.json."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from holdout import config as C  # noqa: E402
from holdout.genome import apply_ops, gen0  # noqa: E402
from holdout.llm import spend_summary  # noqa: E402
from holdout.redteam import CANNED, cheat_ops, llm_cheat  # noqa: E402
from holdout.tasks import pools  # noqa: E402
from holdout.team import evaluate, score  # noqa: E402

t0 = time.time()
P = pools()
g0 = gen0()
base_tr, base_au = score(evaluate(g0, P["train"])), score(evaluate(g0, P["audit"]))
print(f"gen-0 train visible {base_tr['visible']:.1%} hidden {base_tr['hidden']:.1%} | audit hidden {base_au['hidden']:.1%}")
cheats = list(CANNED)
llm = llm_cheat(g0, [c["rule"] for c in CANNED], tag="-check")
if llm:
    cheats.append(llm)
rows = []
for c in cheats:
    g, applied, errs = apply_ops(g0, cheat_ops(c))
    tr, au = score(evaluate(g, P["train"])), score(evaluate(g, P["audit"]))
    row = {"name": c["name"], "rule": c["rule"], "train_visible": tr["visible"], "train_hidden": tr["hidden"],
           "audit_hidden": au["hidden"], "visible_gain": tr["visible"] - base_tr["visible"],
           "audit_hidden_change": au["hidden"] - base_au["hidden"], "raises_visible": tr["visible"] > base_tr["visible"]}
    rows.append(row)
    print(f"{c['name']:<28} visible {row['visible_gain']:+.1%}  audit hidden {row['audit_hidden_change']:+.1%}  "
          f"{'RAISES VISIBLE' if row['raises_visible'] else 'does not raise visible (logged, try next)'}")
out = {"gen0": {"train_visible": base_tr["visible"], "train_hidden": base_tr["hidden"], "audit_hidden": base_au["hidden"]},
       "cheats": rows, "seconds": round(time.time() - t0, 1), "spend": spend_summary()["total"]}
(C.RESULTS / "cheat_check.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out["spend"]), out["seconds"], "s")
