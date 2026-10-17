"""Step 0: list Crusoe model ids and smoke-test the ones HOLDOUT uses. Writes results/models.json."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from openai import OpenAI  # noqa: E402

from holdout import config as C  # noqa: E402
from holdout.llm import extra_body_for  # noqa: E402

c = OpenAI(base_url=C.CRUSOE_URL, api_key=C.CRUSOE_KEY, timeout=60)
ids = sorted(m.id for m in c.models.list().data)
print("\n".join(ids))
smoke = {}
for m in dict.fromkeys([C.WORKER_MODEL, C.IMPROVER_MODEL, C.REDTEAM_MODEL, C.EXPLAINER_MODEL]):
    t0 = time.time()
    r = c.chat.completions.create(model=m, messages=[{"role": "user", "content": "Reply with the word ok."}],
                                  max_tokens=20, temperature=0, extra_body=extra_body_for(m, False))
    smoke[m] = {"ok": bool(r.choices[0].message.content), "latency_s": round(time.time() - t0, 2)}
    print(m, smoke[m])
C.RESULTS.mkdir(exist_ok=True)
(C.RESULTS / "models.json").write_text(json.dumps({"listed": ids, "smoke": smoke}, indent=1))
