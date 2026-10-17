"""Generations, both arms. Same gen-0, same improver, same red team; only the acceptance rule differs.

  naive:   accept the highest-visible candidate if it beats the current genome's train visible score.
  HOLDOUT: same pick, then it must also pass the Ladder gate on the audit pool's hidden tests.

Usage: python -m holdout.evolve [--gens 4] [--commit] [--run-id ID]
       SEED=23 python -m holdout.evolve --run-id seed23 --aux   # another pool split, kept under runs/seed23/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from rich.console import Console

from . import config as C
from .gate import Ladder
from .genome import apply_ops, describe_ops, gen0, genome_hash, save
from .improver import explain, propose
from .llm import spend_summary
from .redteam import CANNED, cheat_ops, llm_cheat
from .tasks import pools
from .team import evaluate, score

con = Console()
ARMS = ("naive", "holdout")


class Run:
    def __init__(self, run_id: str):
        self.id = run_id
        self.dir = C.RUNS / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events = open(self.dir / "events.jsonl", "w")

    def emit(self, **ev):
        ev["t"] = round(time.time(), 2)
        self.events.write(json.dumps(ev) + "\n")
        self.events.flush()


def eval_genome(g: dict) -> dict:
    P = pools()
    tr, au = evaluate(g, P["train"]), evaluate(g, P["audit"])
    return {"genome": g, "hash": genome_hash(g), "train_results": tr, "train": score(tr), "audit": score(au)}


def _summary(ev: dict) -> dict:
    return {"train_visible": ev["train"]["visible"], "train_hidden": ev["train"]["hidden"],
            "audit_visible": ev["audit"]["visible"], "audit_hidden": ev["audit"]["hidden"], "hash": ev["hash"],
            "calls_per_task": (ev["train"]["calls"] + ev["audit"]["calls"]) / (ev["train"]["n"] + ev["audit"]["n"])}


def _commit(msg: str) -> None:
    subprocess.run(["git", "add", "--", "genomes"], cwd=C.ROOT, check=False)
    subprocess.run(["git", "commit", "-q", "-m", msg + "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
                    "--", "genomes"], cwd=C.ROOT, check=False)


def next_cheat(arm_state: dict, cur: dict, gen: int) -> tuple[dict, dict]:
    """Next planted cheat that actually raises visible over `cur`; ineffective ones are logged and skipped (max 3 tries)."""
    log = []
    for _ in range(3):
        i = arm_state["cheat_i"]
        arm_state["cheat_i"] += 1
        if i < len(CANNED):
            ch = CANNED[i]
        else:
            ch = llm_cheat(cur["genome"], [c["rule"] for c in CANNED] + arm_state["llm_cheats"], tag=f"-g{gen}-{i}")
            if not ch:
                continue
            arm_state["llm_cheats"].append(ch["rule"])
        g, applied, _ = apply_ops(cur["genome"], cheat_ops(ch))
        if not applied:
            log.append({"name": ch["name"], "skipped": "could not apply"})
            continue
        ev = eval_genome(g)
        gain = ev["train"]["visible"] - cur["train"]["visible"]
        if gain > 0:
            return {"kind": "redteam", "planted": True, "name": ch["name"], "ops": applied, "rationale": ch["rule"],
                    "eval": ev}, {"ineffective": log}
        log.append({"name": ch["name"], "visible_gain": gain, "skipped": "does not raise visible"})
    return {}, {"ineffective": log}


def run(gens: int = C.GENERATIONS, commit: bool = False, run_id: str | None = None, live: bool = False) -> dict:
    """live=True (demo.py --live): genomes and results stay inside runs/<id>/, never touching the committed ones."""
    run_id = run_id or time.strftime("evolve_%Y%m%d_%H%M%S")
    R = Run(run_id)
    groot = (R.dir / "genomes") if live else C.GENOMES
    commit = commit and not live
    t0 = time.time()
    g0 = gen0()
    e0 = eval_genome(g0)
    s0 = _summary(e0)
    con.print(f"[bold]gen-0[/] train visible {s0['train_visible']:.1%}  audit hidden {s0['audit_hidden']:.1%}")
    R.emit(type="gen0", **s0, genome=g0)
    for arm in ARMS:
        save(g0, arm, 0, groot)
    if commit:
        _commit("evolve gen 0: both arms start from the same minimal genome")

    ladder = Ladder(C.N_AUDIT)
    ladder.submit(e0["audit"]["losses"])  # R_0 = inf: gen-0 sets the gate's baseline
    state = {a: {"cur": e0, "history": [], "cheat_i": 0, "llm_cheats": [], "gens": [dict(gen=0, **s0)]} for a in ARMS}
    gate_log, planted, explained = [], [], []

    for gen in range(1, gens + 1):
        R.emit(type="gen_start", gen=gen)
        con.rule(f"generation {gen}")

        def build(arm):
            st = state[arm]
            cur = st["cur"]
            props = propose(cur["genome"], cur["train_results"], st["history"], tag=f"-{cur['hash']}")
            cands = []
            for p in props:
                g, applied, errs = apply_ops(cur["genome"], p["ops"])
                if applied and genome_hash(g) != cur["hash"]:
                    cands.append({"kind": "improver", "planted": False, "name": "improver", "ops": applied,
                                  "rationale": p["rationale"], "genome": g, "op_errors": errs})
            with ThreadPoolExecutor(len(cands) or 1) as ex:
                evs = list(ex.map(lambda c: eval_genome(c["genome"]), cands))
            for c, ev in zip(cands, evs):
                c["eval"] = ev
            ch, chlog = next_cheat(st, cur, gen)
            if ch:
                cands.append(ch)
            return arm, cands, chlog

        with ThreadPoolExecutor(2) as ex:
            built = list(ex.map(build, ARMS))

        for arm, cands, chlog in built:
            st = state[arm]
            cur = st["cur"]
            for k, c in enumerate(cands):
                ev = c["eval"]
                c["visible_gain"] = ev["train"]["visible"] - cur["train"]["visible"]
                c["audit_hidden_gain"] = ev["audit"]["hidden"] - cur["audit"]["hidden"]  # logs only
                R.emit(type="candidate", arm=arm, gen=gen, idx=k, kind=c["kind"], planted=c["planted"], name=c["name"],
                       ops=describe_ops(c["ops"]), rationale=c["rationale"], train_visible=ev["train"]["visible"],
                       visible_gain=c["visible_gain"], audit_hidden=ev["audit"]["hidden"],
                       audit_hidden_gain=c["audit_hidden_gain"], hash=ev["hash"])
            for x in chlog["ineffective"]:
                R.emit(type="cheat_ineffective", arm=arm, gen=gen, **x)

            best = max(cands, key=lambda c: (c["eval"]["train"]["visible"], -c["eval"]["train"]["calls"])) if cands else None
            accepted, verdict = False, None
            if best and best["visible_gain"] > 0:
                if arm == "naive":
                    accepted, reason = True, f"visible +{best['visible_gain']:.1%}"
                else:
                    v = ladder.submit(best["eval"]["audit"]["losses"])
                    accepted, reason = v.accepted, v.reason
                    verdict = {"accepted": v.accepted, "reported_score": v.reported_score, "reason": v.reason}
            else:
                reason = "no candidate beats current visible score"

            for k, c in enumerate(cands):
                row = {"arm": arm, "gen": gen, "idx": k, "kind": c["kind"], "planted": c["planted"], "name": c["name"],
                       "ops": describe_ops(c["ops"]), "visible_gain": c["visible_gain"],
                       "audit_hidden_gain": c["audit_hidden_gain"], "selected": c is best,
                       "accepted": accepted and c is best,
                       "verdict": (reason if c is best else "not selected (lower visible score)")}
                gate_log.append(row)
                if c["planted"]:
                    planted.append(row)

            R.emit(type="verdict", arm=arm, gen=gen, accepted=accepted, reason=reason,
                   idx=cands.index(best) if best else None, gate=verdict,
                   visible_gain=best["visible_gain"] if best else 0, planted=bool(best and best["planted"]))
            tag = f"{arm.upper():<8}"
            if best:
                con.print(f"{tag} {'ACCEPTED' if accepted else 'rejected'} ({reason}) "
                          f"visible {best['visible_gain']:+.1%}: {describe_ops(best['ops'])[:100]}")
            if accepted:
                if arm == "naive" and best["visible_gain"] > 0 and best["audit_hidden_gain"] <= 0:
                    lab = explain(best["ops"], best["visible_gain"], best["audit_hidden_gain"])
                    explained.append({"gen": gen, "ops": describe_ops(best["ops"]), "planted": best["planted"],
                                      "visible_gain": best["visible_gain"], "audit_hidden_gain": best["audit_hidden_gain"], **lab})
                    R.emit(type="explainer", arm=arm, gen=gen, **lab)
                st["cur"] = best["eval"]
            for c in cands:
                outcome = "accepted" if (accepted and c is best) else "rejected"
                note = f" (gate: {verdict['reason']})" if (arm == "holdout" and c is best and verdict) else ""
                st["history"].append(f"gen {gen}: {describe_ops(c['ops'])[:160]} -> visible {c['visible_gain']:+.1%}, "
                                     f"{outcome}{note}")
            save(st["cur"]["genome"], arm, gen, groot)
            st["gens"].append({"gen": gen, **_summary(st["cur"]), "accepted": accepted, "reason": reason,
                               "accepted_ops": describe_ops(best["ops"]) if accepted else None,
                               "accepted_planted": bool(accepted and best["planted"])})
            R.emit(type="gen_end", arm=arm, gen=gen, **_summary(st["cur"]))
        if commit:
            n, h = state["naive"]["gens"][-1], state["holdout"]["gens"][-1]
            _commit(f"evolve gen {gen}: naive {'accepted' if n['accepted'] else 'kept'} "
                    f"(visible {n['train_visible']:.1%}), holdout {'accepted' if h['accepted'] else 'kept'} "
                    f"(visible {h['train_visible']:.1%})")
        sp = spend_summary()["total"]
        con.print(f"[dim]spend so far ~${sp['usd']:.3f}, {sp['calls']} calls, {sp['tokens_in'] + sp['tokens_out']:,} tokens, "
                  f"{time.time() - t0:.0f}s[/]")

    res = {"run_id": run_id, "seconds": round(time.time() - t0, 1),
           "config": {"worker": C.WORKER_MODEL, "improver": C.IMPROVER_MODEL, "redteam": C.REDTEAM_MODEL,
                      "explainer": C.EXPLAINER_MODEL, "seed": C.SEED, "generations": gens, "P": C.P_IMPROVER,
                      "pools": {k: len(v) for k, v in pools().items()}},
           "gen0": s0, "arms": {a: state[a]["gens"] for a in ARMS},
           "final_hash": {a: state[a]["cur"]["hash"] for a in ARMS},
           "planted": planted, "gate_log": gate_log, "explainer": explained,
           "ladder": [{k: v for k, v in h.items()} for h in ladder.history], "spend_evolve": spend_summary()}
    if not live:
        C.RESULTS.mkdir(exist_ok=True)
        (C.RESULTS / "results.json").write_text(json.dumps(res, indent=1))
    (R.dir / "results.json").write_text(json.dumps(res, indent=1))
    R.emit(type="done", seconds=res["seconds"])
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gens", type=int, default=C.GENERATIONS)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--aux", action="store_true", help="extra seed: keep genomes/results inside runs/<id>/")
    a = ap.parse_args()
    run(a.gens, a.commit, a.run_id, live=a.aux)
