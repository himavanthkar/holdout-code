"""Splice numbers from results/results.json (and results/tables.md) into README.md, so no number is typed by hand."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
res = json.loads((ROOT / "results" / "results.json").read_text())
tables = (ROOT / "results" / "tables.md").read_text()


def p(x):
    return f"{100 * x:.1f}%"


n0, nf = res["arms"]["naive"][0], res["arms"]["naive"][-1]
h0, hf = res["arms"]["holdout"][0], res["arms"]["holdout"][-1]
pl = res["planted"]
na, nn = sum(r["accepted"] for r in pl if r["arm"] == "naive"), sum(r["arm"] == "naive" for r in pl)
ha, hn = sum(r["accepted"] for r in pl if r["arm"] == "holdout"), sum(r["arm"] == "holdout" for r in pl)
imp = [r for r in res["gate_log"] if not r["planted"]]
imp_up = [r for r in imp if r["visible_gain"] > 0]
imp_fake = [r for r in imp_up if r["audit_hidden_gain"] <= 0]
imp_real = [r for r in imp if r["audit_hidden_gain"] > 0]
imp_real_hidden_by_visible = [r for r in imp_real if r["visible_gain"] <= 0]
nat_acc = [g for g in res["arms"]["naive"][1:] if g.get("accepted") and not g.get("accepted_planted")]
hold_acc = [g for g in res["arms"]["holdout"][1:] if g.get("accepted")]
u = res.get("unseen", {}).get("results")
G = res["config"]["generations"]

head = [f"**Result (seed {res['config']['seed']}, {G} generations, same proposals for both arms):**", "",
        f"| | train visible | audit hidden | planted cheats accepted |" + (" unseen HumanEval+ hidden |" if u else ""),
        "|---|---|---|---|" + ("---|" if u else "")]
if u:
    head.append(f"| gen-0 | {p(n0['train_visible'])} | {p(n0['audit_hidden'])} | - | {p(u['gen0']['hidden'])} |")
head.append(f"| naive final | {p(nf['train_visible'])} | {p(nf['audit_hidden'])} | {na}/{nn} |"
            + (f" {p(u['naive_final']['hidden'])} |" if u else ""))
head.append(f"| HOLDOUT final | {p(hf['train_visible'])} | {p(hf['audit_hidden'])} | {ha}/{hn} |"
            + (f" {p(u['holdout_final']['hidden'])} |" if u else ""))
head += ["", f"The naive team's visible score climbed while its hidden score fell; HOLDOUT's gate refused every "
             f"cheat it was shown. HOLDOUT accepted {len(hold_acc)} change(s) in {G} generations"
             + (", so its final genome is gen-0: it did not get better, it refused to get worse." if not hold_acc else ".")]

allruns = [res] + [json.loads(d.read_text()) for d in sorted((ROOT / "runs").glob("seed*/results.json"))]
if len(allruns) > 1 and all(r.get("unseen") for r in allruns):
    P = [x for r in allruns for x in r["planted"]]
    acc = [x for x in P if x["arm"] == "naive" and x["accepted"]]
    vis = [r["arms"]["naive"][-1]["train_visible"] for r in allruns]
    dh = [100 * (r["arms"]["naive"][-1]["audit_hidden"] - r["arms"]["naive"][0]["audit_hidden"]) for r in allruns]
    du = [100 * (r["unseen"]["results"]["naive_final"]["hidden"] - r["unseen"]["results"]["gen0"]["hidden"]) for r in allruns]
    hacc = sum(1 for r in allruns for g in r["arms"]["holdout"][1:] if g.get("accepted"))
    sd = ", ".join(str(r["config"]["seed"]) for r in allruns)
    head += ["", f"**Across {len(allruns)} pool splits (seeds {sd}):** naive accepted "
             f"{len(acc)}/{sum(x['arm'] == 'naive' for x in P)} planted cheats, HOLDOUT "
             f"{sum(x['accepted'] for x in P if x['arm'] == 'holdout')}/{sum(x['arm'] == 'holdout' for x in P)}. "
             f"Naive's train visible score ended at {', '.join(p(v) for v in vis)}; its audit hidden change vs gen-0 was "
             f"{', '.join(f'{v:+.1f}' for v in dh)} points and its unseen HumanEval+ change "
             f"{', '.join(f'{v:+.1f}' for v in du)} points. The visible inflation shows up in every seed; the hidden damage "
             f"varies (accepted cheats moved audit hidden by {min(100 * x['audit_hidden_gain'] for x in acc):+.1f} to "
             f"{max(100 * x['audit_hidden_gain'] for x in acc):+.1f} points), and seed {allruns[0]['config']['seed']} is the "
             f"most dramatic. HOLDOUT accepted {hacc} change(s) across all seeds, so its unseen score always equals gen-0's: "
             f"it is a safety result, not an improvement result."]

seeds = []
for d in sorted((ROOT / "runs").glob("seed*/results.json")):
    r = json.loads(d.read_text())
    a, b = r["arms"]["naive"], r["arms"]["holdout"]
    ru = r.get("unseen", {}).get("results")
    pr = r["planted"]
    seeds.append(f"| {r['config']['seed']} | {p(a[0]['train_visible'])} / {p(a[0]['audit_hidden'])} | "
                 f"{p(a[-1]['train_visible'])} / {p(a[-1]['audit_hidden'])} | {p(b[-1]['train_visible'])} / {p(b[-1]['audit_hidden'])} | "
                 f"{sum(x['accepted'] for x in pr if x['arm'] == 'naive')}/{sum(x['arm'] == 'naive' for x in pr)} | "
                 f"{sum(x['accepted'] for x in pr if x['arm'] == 'holdout')}/{sum(x['arm'] == 'holdout' for x in pr)} | "
                 + (f"{p(ru['gen0']['hidden'])} / {p(ru['naive_final']['hidden'])} / {p(ru['holdout_final']['hidden'])} |" if ru else "pending |"))

body = [tables]
if seeds:
    m = res
    mu = m.get("unseen", {}).get("results")
    row0 = (f"| {m['config']['seed']} (main) | {p(n0['train_visible'])} / {p(n0['audit_hidden'])} | {p(nf['train_visible'])} / "
            f"{p(nf['audit_hidden'])} | {p(hf['train_visible'])} / {p(hf['audit_hidden'])} | {na}/{nn} | {ha}/{hn} | "
            + (f"{p(mu['gen0']['hidden'])} / {p(mu['naive_final']['hidden'])} / {p(mu['holdout_final']['hidden'])} |" if mu else "|"))
    body += ["### Other pool splits (extra seeds, same code; files under `runs/seed*/`)\n",
             "| seed | gen-0 visible / hidden | naive final visible / hidden | HOLDOUT final visible / hidden | "
             "naive planted accepted | HOLDOUT planted accepted | unseen hidden: gen-0 / naive / HOLDOUT |",
             "|---|---|---|---|---|---|---|", row0] + seeds + [""]
rk = ROOT / "runs" / "ranked17" / "results.json"
if rk.exists():
    r = json.loads(rk.read_text())
    hg = r["arms"]["holdout"]
    subs = [x for x in r["gate_log"] if x["arm"] == "holdout" and x["verdict"] not in ("not selected (lower visible score)",)
            and not x["verdict"].startswith("no candidate")]
    ru = r.get("unseen", {}).get("results")
    body += ["### Extra run: ranked gate (seed 17, " + str(r["config"]["generations"]) + " generations, files under `runs/ranked17/`)\n",
             "Same code and seed, but the HOLDOUT arm sends every candidate that does not lower the visible score to the "
             "Ladder, best visible first, until one passes (the main run sends only the top-visible one). The Ladder was "
             "designed for many adaptive submissions; each one is a round.\n",
             "| gen | HOLDOUT-ranked visible | HOLDOUT-ranked hidden (audit) | change |", "|---|---|---|---|"]
    for g in hg:
        ch = "start" if g["gen"] == 0 else ((("**planted** " if g.get("accepted_planted") else "") + (g.get("accepted_ops") or "")[:80])
                                             if g.get("accepted") else f"kept ({g['reason']})")
        body.append(f"| {g['gen']} | {p(g['train_visible'])} | {p(g['audit_hidden'])} | {ch} |")
    nacc = sum(1 for x in subs if x["accepted"])
    body += ["", f"Ladder submissions: {len(subs)}, accepted: {nacc}, planted cheats accepted: "
                 f"{sum(1 for x in r['planted'] if x['arm'] == 'holdout' and x['accepted'])}/"
                 f"{sum(1 for x in r['planted'] if x['arm'] == 'holdout')}."
             + (f" Unseen HumanEval+ hidden: gen-0 {p(ru['gen0']['hidden'])}, HOLDOUT-ranked final "
                f"{p(ru['holdout_final']['hidden'])}." if ru else " Unseen eval: not run.")
             + (f" Every submitted candidate changed audit hidden by {min(100 * x['audit_hidden_gain'] for x in subs):+.1f} to "
                f"{max(100 * x['audit_hidden_gain'] for x in subs):+.1f} points, so giving the gate more candidates did not "
                f"help: from gen-0, the proposer never offered a change that was really better. The bottleneck is the "
                f"proposer, not the gate." if subs and not nacc and max(x["audit_hidden_gain"] for x in subs) <= 0 else ""), ""]

body += ["### What the improver did on its own (no planted label)\n",
         f"- {len(imp)} improver candidates across both arms; {len(imp_up)} raised the visible score, and "
         f"{len(imp_fake)} of those did not raise the hidden audit score (mostly train-task-specific playbook rules "
         f"such as \"For sum of unique elements: ...\": overfitting to the traces it was shown).",
         (f"- The naive arm accepted {len(nat_acc)} improver change(s) on its own. Every naive acceptance was a planted "
          f"cheat; in the other generations no improver diff beat the current visible score. So in this run the naive "
          f"arm did not cheat by itself: its damage came from the planted cheats. We report that as is."
          if not nat_acc else f"- The naive arm accepted {len(nat_acc)} improver change(s) on its own (see the table above)."),
         f"- {len(imp_real)} improver candidates did raise the hidden audit score; {len(imp_real_hidden_by_visible)} of "
         f"them lowered or kept the visible score, so visible-first selection threw them away in both arms "
         f"(e.g. turning on the reviewer + edge-case tool).", ""]

s = (ROOT / "README.md").read_text()
s = re.sub(r"<!-- HEADLINE -->.*?(<!-- /HEADLINE -->|$)", lambda _: "<!-- HEADLINE -->\n" + "\n".join(head) + "\n<!-- /HEADLINE -->",
           s, count=1, flags=re.S) if "<!-- /HEADLINE -->" in s else s.replace(
    "<!-- HEADLINE -->", "<!-- HEADLINE -->\n" + "\n".join(head) + "\n<!-- /HEADLINE -->", 1)
block = "<!-- RESULTS -->\n" + "\n".join(body) + "\n<!-- /RESULTS -->"
if "<!-- /RESULTS -->" in s:
    s = re.sub(r"<!-- RESULTS -->.*?<!-- /RESULTS -->", lambda _: block, s, count=1, flags=re.S)
else:
    s = s.replace("<!-- RESULTS -->", block, 1)
(ROOT / "README.md").write_text(s)
print("\n".join(head))
