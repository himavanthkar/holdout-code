"""The N+1 proof: gen-0, naive-final and HOLDOUT-final on the unseen HumanEval+ pool (a benchmark never used before).

Usage: python -m holdout.final_eval
"""
from __future__ import annotations

import json
import time

from rich.console import Console

from . import config as C
from .genome import load
from .llm import spend_summary
from .tasks import pools
from .team import evaluate, score

con = Console()


def efficiency() -> dict:
    """From the raw call log: real (non-disk-cached) calls, tokens, Crusoe-reported cached prompt tokens, est. $."""
    f = C.RUNS / "logs" / "llm_calls.jsonl"
    rows = [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []
    live = [r for r in rows if not r.get("cached")]
    by = {}
    for r in live:
        m = by.setdefault(r["model"], {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cached_in": 0})
        m["calls"] += 1
        m["tokens_in"] += r["tokens_in"]
        m["tokens_out"] += r["tokens_out"]
        m["cached_in"] += r.get("cached_in", 0) or 0
    usd = sum((m["tokens_in"] * C.PRICES.get(k, (0.5, 2))[0] + m["tokens_out"] * C.PRICES.get(k, (0.5, 2))[1]) / 1e6
              for k, m in by.items())
    tin = sum(m["tokens_in"] for m in by.values())
    cin = sum(m["cached_in"] for m in by.values())
    return {"by_model": by, "live_calls": len(live), "disk_cache_hits": len(rows) - len(live), "tokens_in": tin,
            "tokens_out": sum(m["tokens_out"] for m in by.values()), "crusoe_cached_prompt_tokens": cin,
            "crusoe_cached_share": (cin / tin) if tin else 0.0, "est_usd": usd}


def main(run_dir=None) -> dict:
    """run_dir=None: the main run (results/ + genomes/). run_dir=runs/seedNN: an extra seed (same unseen pool)."""
    rpath = (run_dir / "results.json") if run_dir else (C.RESULTS / "results.json")
    groot = (run_dir / "genomes") if run_dir else C.GENOMES
    res = json.loads(rpath.read_text())
    G = res["config"]["generations"]
    genomes = {"gen0": load(groot / "naive" / "gen_0.yaml"),
               "naive_final": load(groot / "naive" / f"gen_{G}.yaml"),
               "holdout_final": load(groot / "holdout" / f"gen_{G}.yaml")}
    items = pools()["unseen"]
    t0 = time.time()
    out = {"n": len(items), "benchmark": "HumanEval+", "results": {}}
    for name, g in genomes.items():
        s = score(evaluate(g, items))
        out["results"][name] = {"hidden": s["hidden"], "visible": s["visible"], "calls": s["calls"], "tokens": s["tokens"]}
        con.print(f"{name:<14} unseen HumanEval+ hidden {s['hidden']:.1%}  visible {s['visible']:.1%}")
    out["seconds"] = round(time.time() - t0, 1)
    eff = efficiency()
    gain = out["results"]["holdout_final"]["hidden"] - out["results"]["gen0"]["hidden"]
    eff["usd_per_point_holdout_unseen_gain"] = (eff["est_usd"] / (gain * 100)) if gain > 0 else None
    res["unseen"] = out
    res["efficiency"] = eff
    rpath.write_text(json.dumps(res, indent=1))
    con.print(f"[dim]est. total spend ${eff['est_usd']:.3f}, {eff['live_calls']} live calls, "
              f"Crusoe cached share {eff['crusoe_cached_share']:.1%}[/]")
    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path

    main(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None)
