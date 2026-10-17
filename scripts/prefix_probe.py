"""MemoryAlloy probe: Nano reports no cached_tokens, so compare time-to-first-token for a SHARED genome prefix vs a
SHUFFLED one (same length, a nonce at the front breaks prefix reuse). Writes results/prefix_probe.json."""
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from openai import OpenAI  # noqa: E402

from holdout import config as C  # noqa: E402
from holdout.genome import gen0  # noqa: E402
from holdout.llm import extra_body_for  # noqa: E402
from holdout.tasks import pools, public_task  # noqa: E402
from holdout.team import system_prompt, task_message  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
cl = OpenAI(base_url=C.CRUSOE_URL, api_key=C.CRUSOE_KEY, timeout=60)
g = gen0()
g["playbook"] = [f"Rule {i}: " + "Prefer clear, standard-library solutions and handle edge cases explicitly. " * 6
                 for i in range(10)]  # a realistic full playbook, ~800 tokens
prefix = system_prompt(g, "solver")
tasks = [public_task(*it) for it in pools()["train"][:N]]


def ttft(system: str, user: str) -> float:
    t0 = time.time()
    s = cl.chat.completions.create(model=C.WORKER_MODEL, stream=True, max_tokens=8, temperature=0,
                                   messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                                   extra_body=extra_body_for(C.WORKER_MODEL, False))
    for chunk in s:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            break
    dt = time.time() - t0
    for _ in s:
        pass
    return dt


ttft(prefix, "warm up")
shared, shuffled = [], []
for t in tasks:
    user = task_message(t, g)
    shared.append(ttft(prefix, user))
    shuffled.append(ttft(f"[session {random.random():.12f}]\n" + prefix, user))
out = {"n": N, "model": C.WORKER_MODEL, "prefix_chars": len(prefix),
       "ttft_shared_median_s": statistics.median(shared), "ttft_shuffled_median_s": statistics.median(shuffled),
       "shared": shared, "shuffled": shuffled}
print(json.dumps({k: v for k, v in out.items() if k not in ("shared", "shuffled")}, indent=1))
(C.RESULTS / "prefix_probe.json").write_text(json.dumps(out, indent=1))
