"""Gen-0 headroom check on the 20-task smoke pool (disjoint from train/audit/unseen). Wants hidden in [40%, 75%]."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from holdout import config as C  # noqa: E402
from holdout.genome import gen0  # noqa: E402
from holdout.llm import spend_summary  # noqa: E402
from holdout.tasks import pools  # noqa: E402
from holdout.team import evaluate, score  # noqa: E402

model = sys.argv[1] if len(sys.argv) > 1 else C.WORKER_MODEL
g = gen0()
for r in g["roles"].values():
    r["model"] = model
t0 = time.time()
res = evaluate(g, pools()["smoke"])
s = score(res)
row = {"model": model, "visible": s["visible"], "hidden": s["hidden"], "n": s["n"], "calls": s["calls"],
       "seconds": round(time.time() - t0, 1), "spend": spend_summary()["total"]}
print(json.dumps(row, indent=1))
C.RESULTS.mkdir(exist_ok=True)
p = C.RESULTS / "headroom.json"
prev = json.loads(p.read_text()) if p.exists() else []
p.write_text(json.dumps([x for x in prev if x["model"] != model] + [row], indent=1))
