"""Charts (matplotlib PNG) and markdown tables, from results/results.json only.

Usage: python -m holdout.report
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import config as C  # noqa: E402

NAIVE, HOLD = "#c2410c", "#1d4ed8"


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def chart_lines(res: dict, path):
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=150)
    for arm, col, lab in (("naive", NAIVE, "Naive"), ("holdout", HOLD, "HOLDOUT")):
        gens = res["arms"][arm]
        xs = [g["gen"] for g in gens]
        ax.plot(xs, [100 * g["train_visible"] for g in gens], "-o", color=col, lw=2.2, label=f"{lab}: visible (train)")
        ax.plot(xs, [100 * g["audit_hidden"] for g in gens], "--s", color=col, lw=2.2, alpha=0.8,
                label=f"{lab}: hidden (audit)")
        for g in gens[1:]:
            if g.get("accepted_planted"):
                ax.annotate("planted cheat\naccepted", (g["gen"], 100 * g["train_visible"]), textcoords="offset points",
                            xytext=(0, 10), ha="center", fontsize=7, color=col)
    lo = min(100 * g[k] for arm in ("naive", "holdout") for g in res["arms"][arm] for k in ("train_visible", "audit_hidden"))
    ax.set_ylim(max(0, lo - 8), 110)
    ax.set_xlabel("generation")
    ax.set_ylabel("pass rate (%)")
    ax.set_xticks([g["gen"] for g in res["arms"]["naive"]])
    ax.set_title("Visible score vs hidden truth, per generation")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7.5, loc="lower left", ncol=2)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def chart_planted(res: dict, path):
    rows = res["planted"]
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    labels = [f"{r['arm']} g{r['gen']}\n{r['name']}" for r in rows]
    xs = range(len(rows))
    ax.bar([x - 0.2 for x in xs], [100 * r["visible_gain"] for r in rows], 0.4, color="#64748b", label="visible gain (train)")
    ax.bar([x + 0.2 for x in xs], [100 * r["audit_hidden_gain"] for r in rows], 0.4, color="#dc2626",
           label="hidden change (audit)")
    for x, r in zip(xs, rows):
        ax.text(x, max(100 * r["visible_gain"], 0) + 1, "ACCEPTED" if r["accepted"] else "rejected", ha="center",
                fontsize=7, color=NAIVE if r["accepted"] else HOLD, fontweight="bold")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(list(xs))
    ax.set_xticklabels(labels, fontsize=6.5)
    ax.set_ylabel("percentage points")
    ax.set_title("Planted cheats: visible gain vs hidden change, and who accepted them")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def chart_unseen(res: dict, path):
    u = res.get("unseen")
    if not u:
        return
    names = [("gen0", "gen-0"), ("naive_final", "naive final"), ("holdout_final", "HOLDOUT final")]
    vals = [100 * u["results"][k]["hidden"] for k, _ in names]
    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
    bars = ax.bar([n for _, n in names], vals, color=["#94a3b8", NAIVE, HOLD])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.1f}%", ha="center", fontsize=9)
    ax.set_ylim(0, 100)
    ax.set_ylabel("hidden (plus) pass rate (%)")
    ax.set_title(f"Unseen {u['benchmark']} ({u['n']} tasks, never used during evolution)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def tables(res: dict) -> str:
    out = ["### Per generation (train visible / audit hidden)\n",
           "| gen | naive visible | naive hidden | naive change | HOLDOUT visible | HOLDOUT hidden | HOLDOUT change |",
           "|---|---|---|---|---|---|---|"]
    for n, h in zip(res["arms"]["naive"], res["arms"]["holdout"]):
        def ch(g):
            if g["gen"] == 0:
                return "start"
            if not g.get("accepted"):
                return f"kept ({g['reason']})"
            return ("**planted** " if g.get("accepted_planted") else "") + (g.get("accepted_ops") or "")[:70]
        out.append(f"| {n['gen']} | {pct(n['train_visible'])} | {pct(n['audit_hidden'])} | {ch(n)} | "
                   f"{pct(h['train_visible'])} | {pct(h['audit_hidden'])} | {ch(h)} |")
    out += ["\n### Planted cheats\n", "| arm | gen | cheat | visible gain | audit hidden change | accepted |", "|---|---|---|---|---|---|"]
    for r in res["planted"]:
        out.append(f"| {r['arm']} | {r['gen']} | {r['name']} | {100 * r['visible_gain']:+.1f} | "
                   f"{100 * r['audit_hidden_gain']:+.1f} | {'yes' if r['accepted'] else 'no'} |")
    na = sum(r["accepted"] for r in res["planted"] if r["arm"] == "naive")
    ha = sum(r["accepted"] for r in res["planted"] if r["arm"] == "holdout")
    nn = sum(1 for r in res["planted"] if r["arm"] == "naive")
    hn = sum(1 for r in res["planted"] if r["arm"] == "holdout")
    out.append(f"\nPlanted cheats accepted: naive {na}/{nn}, HOLDOUT {ha}/{hn}.")
    out += ["\n### Gate log (every candidate)\n", "| arm | gen | kind | change | visible gain | audit hidden change | verdict |",
            "|---|---|---|---|---|---|---|"]
    for r in res["gate_log"]:
        kind = "red team" if r["planted"] else "improver"
        out.append(f"| {r['arm']} | {r['gen']} | {kind} | {r['ops'][:80].replace('|', '/')} | {100 * r['visible_gain']:+.1f} | "
                   f"{100 * r['audit_hidden_gain']:+.1f} | {('ACCEPTED: ' if r['accepted'] else '') + r['verdict']} |")
    if res.get("explainer"):
        out += ["\n### Explainer labels (naive-arm fake improvements)\n", "| gen | planted | label | why |", "|---|---|---|---|"]
        for e in res["explainer"]:
            out.append(f"| {e['gen']} | {'yes' if e['planted'] else 'no'} | {e['label']} | {e['why'][:160]} |")
    u = res.get("unseen")
    if u:
        out += [f"\n### Unseen {u['benchmark']} ({u['n']} tasks)\n", "| genome | hidden pass | visible pass | LLM calls |",
                "|---|---|---|---|"]
        for k, lab in (("gen0", "gen-0"), ("naive_final", "naive final"), ("holdout_final", "HOLDOUT final")):
            r = u["results"][k]
            out.append(f"| {lab} | {pct(r['hidden'])} | {pct(r['visible'])} | {r['calls']} |")
    e = res.get("efficiency")
    if e:
        out += ["\n### Efficiency (whole project: checks, evolution, unseen eval)\n", f"- live LLM calls: {e['live_calls']:,} (plus {e['disk_cache_hits']:,} served from the disk cache)",
                f"- tokens: {e['tokens_in']:,} in, {e['tokens_out']:,} out",
                f"- Crusoe-reported cached prompt tokens: {e['crusoe_cached_prompt_tokens']:,} ({pct(e['crusoe_cached_share'])})",
                f"- estimated spend: ${e['est_usd']:.3f} (estimated per-token prices, see config.py)"]
        if e.get("usd_per_point_holdout_unseen_gain"):
            out.append(f"- $ per point of HOLDOUT unseen hidden gain: ${e['usd_per_point_holdout_unseen_gain']:.4f}")
    p = C.RESULTS / "prefix_probe.json"
    if p.exists():
        pp = json.loads(p.read_text())
        out.append(f"- TTFT probe ({pp['n']} calls each, {pp['model']}): shared prefix median "
                   f"{pp['ttft_shared_median_s']:.3f}s vs shuffled prefix {pp['ttft_shuffled_median_s']:.3f}s")
    return "\n".join(out) + "\n"


def main():
    res = json.loads((C.RESULTS / "results.json").read_text())
    chart_lines(res, C.RESULTS / "chart_visible_vs_hidden.png")
    chart_planted(res, C.RESULTS / "chart_planted_cheats.png")
    chart_unseen(res, C.RESULTS / "chart_unseen.png")
    (C.RESULTS / "tables.md").write_text(tables(res))
    print((C.RESULTS / "tables.md").read_text())


if __name__ == "__main__":
    main()
