"""Build the 1-minute demo video from the REAL replay output (no screen recorder needed).

Runs demo.replay(runs/main) into a recording rich console, snapshots the terminal at every pause, renders each
snapshot to PNG (rich SVG -> rsvg-convert), lays the frames on the narration timeline, adds the charts, and muxes
the voiceover.

  python scripts/make_video.py [voiceover.m4a] [--out video/holdout_demo.mp4]
"""
import argparse
import io
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rich.console import Console  # noqa: E402
from rich.text import Text  # noqa: E402

import demo  # noqa: E402

W, LINES = 116, 40
FR = ROOT / "video" / "frames"
# narration timeline (seconds): title, gen-1 detail, gens 2-4 fast, reveal table, main chart, unseen, closing
PLAN = {"title": 8.0, "gen1": 24.0, "fast": 3.0, "reveal": 4.0, "chart": 7.0, "unseen": 8.0, "close": 6.0}


def dur(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def render(ansi: str, path: Path):
    lines = ansi.rstrip("\n").split("\n")[-LINES:]
    c = Console(record=True, width=W, file=io.StringIO(), force_terminal=True, color_system="truecolor")
    c.print(Text.from_ansi("\n".join(lines)))
    svg = path.with_suffix(".svg")
    svg.write_text(c.export_svg(title="holdout-code  $ python demo.py --replay runs/main"))
    subprocess.run(["rsvg-convert", "-w", "1840", "-o", str(path), str(svg)], check=True)
    svg.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", nargs="?", default=str(ROOT / "video" / "voiceover_say.m4a"))
    ap.add_argument("--out", default=str(ROOT / "video" / "holdout_demo.mp4"))
    a = ap.parse_args()
    FR.mkdir(parents=True, exist_ok=True)
    for f in FR.glob("*"):
        f.unlink()

    rec = Console(record=True, width=W, file=io.StringIO(), force_terminal=True, color_system="truecolor")
    demo.con = rec
    snaps = []  # (ansi, plain, natural seconds)
    real_sleep = time.sleep
    time.sleep = lambda s: snaps.append((rec.export_text(clear=False, styles=True), rec.export_text(clear=False), s))
    try:
        demo.replay(ROOT / "runs" / "main", pause=False, speed=1.0)
    finally:
        time.sleep = real_sleep
    final_ansi = rec.export_text(clear=False, styles=True)

    def phase(plain):
        if "generation 2" in plain:
            return "fast"
        if "generation 1" in plain:
            return "gen1"
        return "title"

    items = []  # (png, seconds)
    groups = {"title": [], "gen1": [], "fast": []}
    for i, (ansi, plain, s) in enumerate(snaps):
        if "Both teams say" in plain:
            continue
        groups[phase(plain)].append((i, ansi, s))
    for ph in ("title", "gen1", "fast"):
        g = groups[ph]
        tot = sum(s for _, _, s in g) or 1
        for i, ansi, s in g:
            png = FR / f"f{i:03d}.png"
            render(ansi, png)
            items.append((png, PLAN[ph] * s / tot))
    fin = FR / "final.png"
    render(final_ansi, fin)
    items.append((fin, PLAN["reveal"]))
    items.append((ROOT / "results" / "chart_visible_vs_hidden.png", PLAN["chart"]))
    items.append((ROOT / "results" / "chart_unseen.png", PLAN["unseen"]))
    items.append((fin, PLAN["close"]))

    from PIL import Image  # every shot onto one 1920x1080 canvas: the concat demuxer needs a fixed frame size

    norm = []
    for k, (png, s) in enumerate(items):
        im = Image.open(png).convert("RGB")
        r = min(1880 / im.width, 1060 / im.height, 1.0 if "frames" in str(png) else 9.9)
        im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
        bg = Image.new("RGB", (1920, 1080), (12, 12, 12) if "frames" in str(png) else (255, 255, 255))
        top = 10 if "frames" in str(png) else (1080 - im.height) // 2
        bg.paste(im, ((1920 - im.width) // 2, top))
        out = FR / f"n{k:03d}.png"
        bg.save(out)
        norm.append((out, s))
    items = norm
    lst = FR / "list.txt"
    with open(lst, "w") as f:
        for png, s in items:
            f.write(f"file '{png}'\nduration {s:.3f}\n")
        f.write(f"file '{items[-1][0]}'\n")
    vf = "format=yuv420p,fps=30"
    total = sum(s for _, s in items)
    audio = Path(a.audio)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if audio.exists():
        ad = dur(audio)
        tempo = max(0.8, min(1.25, ad / total))  # fit the narration to the picture timeline
        cmd += ["-i", str(audio), "-filter:a", f"atempo={tempo:.4f},afade=t=out:st={total - 1.5:.2f}:d=1.5",
                "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", f"{total:.2f}", a.out]
    subprocess.run(cmd, check=True)
    print(f"wrote {a.out}: {dur(a.out):.1f}s, {len(items)} shots" + (f", audio tempo {tempo:.3f}" if audio.exists() else ""))


if __name__ == "__main__":
    main()
