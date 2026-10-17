"""HOLDOUT demo: watch two self-improving coding teams evolve, then reveal the hidden tests.

  python demo.py --replay runs/main            # offline: replays a recorded run (no network)
  python demo.py --replay runs/main --no-pause # same, no keypress (for recording)
  python demo.py --live --gens 1               # one small live generation on Crusoe, then replays it
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

ROOT = Path(__file__).resolve().parent
con = Console()
ARM_STYLE = {"naive": "bold dark_orange", "holdout": "bold blue"}


def pct(x):
    return f"{100 * x:.1f}%"


def load(run_dir: Path):
    events = [json.loads(x) for x in (run_dir / "events.jsonl").read_text().splitlines() if x.strip()]
    rp = run_dir / "results.json"
    res = json.loads(rp.read_text()) if rp.exists() else None
    main = ROOT / "results" / "results.json"
    if res and main.exists():
        m = json.loads(main.read_text())
        if m.get("run_id") == res.get("run_id"):
            res = m  # the committed results also carry the unseen eval + efficiency
    return events, res


def replay(run_dir: Path, pause: bool, speed: float):
    events, res = load(run_dir)
    nap = lambda s: time.sleep(s / speed)  # noqa: E731
    con.print(Panel.fit("[bold]HOLDOUT[/]: a coding team that rewrites itself every generation,\n"
                        "but only keeps a change when a test it cannot game proves it is real.\n"
                        "[dim]Two arms, same proposals. NAIVE keeps whatever raises the visible tests. "
                        "HOLDOUT adds a Ladder gate on sealed hidden tests.[/]", border_style="green"))
    cur = {}
    for ev in events:
        t = ev["type"]
        if t == "gen0":
            con.print(f"gen-0 team: solver + 1 repair pass, empty playbook. visible score (train) "
                      f"[bold]{pct(ev['train_visible'])}[/]")
            cur = {"naive": ev["train_visible"], "holdout": ev["train_visible"]}
            nap(1.0)
        elif t == "gen_start":
            con.rule(f"[bold]generation {ev['gen']}[/]")
            nap(0.5)
        elif t == "candidate":
            who = "candidate"
            gain = ev["visible_gain"]
            col = "green" if gain > 0 else ("red" if gain < 0 else "white")
            con.print(f"  [{ARM_STYLE[ev['arm']]}]{ev['arm']:<7}[/] {who} {ev['idx'] + 1}: {ev['ops'][:96]}  "
                      f"[{col}]visible {100 * gain:+.1f}[/]")
            nap(0.35)
        elif t == "cheat_ineffective":
            pass
        elif t == "verdict":
            arm = ev["arm"]
            if ev["accepted"]:
                msg = f"[bold green]accepted[/] (visible +{100 * ev['visible_gain']:.1f})"
            elif ev.get("gate"):
                msg = (f"[bold red]REJECTED[/] ({ev['reason']}) "
                       f"[dim]gate reports audit score {pct(ev['gate']['reported_score'])}[/]")
            else:
                msg = f"kept current genome ({ev['reason']})"
            con.print(f"  [{ARM_STYLE[arm]}]{arm.upper():>7}:[/] {msg}")
            nap(0.8)
        elif t == "explainer":
            con.print(f"  [italic magenta]explainer on naive's change: \"{ev['label']}\" - {ev['why'][:140]}[/]")
            nap(0.8)
        elif t == "gen_end":
            cur[ev["arm"]] = ev["train_visible"]
            if ev["arm"] == "holdout":
                con.print(f"  [dim]visible score now: naive {pct(cur['naive'])}, HOLDOUT {pct(cur['holdout'])}[/]")
                nap(0.6)
    if not res:
        con.print("[yellow]no results.json for this run yet[/]")
        return
    con.print()
    con.print("[bold]Both teams say they improved. Which one actually did?[/]")
    if pause and sys.stdin.isatty():
        con.input("[bold reverse] press Enter to REVEAL HIDDEN TESTS [/] ")
    else:
        nap(1.5)
    reveal(res)


def reveal(res: dict):
    tb = Table(title="Visible (train) vs hidden (audit, EvalPlus plus tests)", show_lines=False)
    tb.add_column("gen", justify="right")
    for arm in ("naive", "holdout"):
        tb.add_column(f"{arm} visible", justify="right", style=ARM_STYLE[arm])
        tb.add_column(f"{arm} hidden", justify="right", style=ARM_STYLE[arm])
    for n, h in zip(res["arms"]["naive"], res["arms"]["holdout"]):
        mark = lambda g: " *" if g.get("accepted_planted") else ""  # noqa: E731
        tb.add_row(str(n["gen"]), pct(n["train_visible"]) + mark(n), pct(n["audit_hidden"]),
                   pct(h["train_visible"]) + mark(h), pct(h["audit_hidden"]))
    con.print(tb)
    con.print("[dim]* = a planted red-team cheat was accepted that generation[/]")
    pl = res["planted"]
    t2 = Table(title="Planted cheats (red team), revealed")
    for c in ("arm", "gen", "cheat", "visible gain", "hidden change", "accepted"):
        t2.add_column(c)
    for r in pl:
        t2.add_row(r["arm"], str(r["gen"]), r["name"], f"{100 * r['visible_gain']:+.1f}",
                   f"{100 * r['audit_hidden_gain']:+.1f}", "[red]YES[/]" if r["accepted"] else "[green]no[/]")
    con.print(t2)
    na = sum(r["accepted"] for r in pl if r["arm"] == "naive")
    ha = sum(r["accepted"] for r in pl if r["arm"] == "holdout")
    con.print(f"planted cheats accepted: [dark_orange]naive {na}/{sum(r['arm'] == 'naive' for r in pl)}[/], "
              f"[blue]HOLDOUT {ha}/{sum(r['arm'] == 'holdout' for r in pl)}[/]")
    u = res.get("unseen")
    if u:
        t3 = Table(title=f"Unseen {u['benchmark']} ({u['n']} tasks, never touched during evolution)")
        t3.add_column("genome")
        t3.add_column("hidden pass", justify="right")
        for k, lab in (("gen0", "gen-0"), ("naive_final", "naive final"), ("holdout_final", "HOLDOUT final")):
            t3.add_row(lab, pct(u["results"][k]["hidden"]))
        con.print(t3)
    e = res.get("efficiency")
    if e:
        con.print(f"[dim]Crusoe: {e['live_calls']:,} live calls, {e['tokens_in'] + e['tokens_out']:,} tokens, "
                  f"~${e['est_usd']:.2f} est.; {e['disk_cache_hits']:,} repeats served from cache[/]")
    con.print("[dim]charts: results/chart_visible_vs_hidden.png, results/chart_planted_cheats.png, "
              "results/chart_unseen.png[/]")
    con.print(Panel.fit("Everyone builds the optimizer. We built the thing that catches it lying.", border_style="green"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", type=Path)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--gens", type=int, default=1)
    ap.add_argument("--no-pause", action="store_true")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--open-charts", action="store_true")
    a = ap.parse_args()
    if a.live:
        from holdout.evolve import run
        rid = time.strftime("live_%H%M%S")
        run(a.gens, commit=False, run_id=rid, live=True)
        a.replay = ROOT / "runs" / rid
    if not a.replay:
        ap.error("pass --replay runs/<id> or --live")
    replay(a.replay if a.replay.is_absolute() else ROOT / a.replay, not a.no_pause, a.speed)
    if a.open_charts:
        for c in ("chart_visible_vs_hidden.png", "chart_planted_cheats.png", "chart_unseen.png"):
            p = ROOT / "results" / c
            if p.exists():
                subprocess.run(["open", str(p)], check=False)


if __name__ == "__main__":
    main()
