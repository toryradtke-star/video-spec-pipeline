"""Show every full-screen shot at a range of pans, so the pan can be picked by eye.

    python scripts/pan_social.py example-product/loop [more ...]

Writes pages/<slug>/social/<name>_pan.jpg — one row per shot, one column per
candidate pan from hard left to hard right, with the shot's current pan marked.

**Why this is needed.** A 9:16 crop keeps ~32% of the width, and the subject a shot
exists to show is centred in maybe a third of them. Left to the default centre crop
the first full-screen batch put a wide painted sign through the right edge and
left a door graphic almost entirely out of frame. There is no way to
compute the right pan — the subject is wherever the camera put it — so the job is
to make choosing fast and a bad choice obvious.

Read a row and pick the column where the subject sits whole and roughly centred. If
no column works, the shot cannot carry full screen: either it needs a different
window of the same clip, or that cut wants `"layout": "card"`.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import render_social as rs
from render30 import esc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "pages")
FONT = config.FONT
PANS = (-1.0, -0.5, 0.0, 0.5, 1.0)
THUMB_W = 200


def sheet(arg):
    slug, _, name = arg.partition("/")
    social = os.path.join(PAGES, slug, "social")
    jobs_p = os.path.join(social, f"{name}_jobs.json")
    if not os.path.exists(jobs_p):
        print(f"  no {os.path.relpath(jobs_p, ROOT)} — run build_social.py first")
        return False
    job = json.load(open(jobs_p, encoding="utf-8"))["jobs"][0]
    if job.get("layout", "full") == "card":
        print(f"  {arg} is a card cut — it does not crop, so there is no pan to pick")
        return True

    tmp = os.path.join(social, "_pan")
    os.makedirs(tmp, exist_ok=True)
    tiles, k = [], 0
    for i, s in enumerate(job["shots"]):
        cur = float(s.get("pan", 0.0))
        # Sample the middle of the shot: the head of a move is not what most of the
        # shot looks like, and the pan has to suit the whole window.
        t = s["start"] + s["dur"] / 2.0
        for p in PANS:
            k += 1
            dest = os.path.join(tmp, f"t{k:03d}.png")
            mark = " <-- now" if abs(p - cur) < 1e-6 else ""
            # esc(): an unescaped colon inside drawtext's text ends the option and
            # ffmpeg reports it as "Error opening output file", nowhere near the cause.
            label = esc(f"{i + 1}: {os.path.basename(s['clip'])[:18]}  pan {p:+.1f}{mark}")
            chain = []
            if s.get("grade") and s["grade"] != "null":
                chain.append(s["grade"])
            if s.get("adjust"):
                chain.append(s["adjust"])
            chain.append(rs.fit_full(p))
            chain.append(f"scale={THUMB_W}:-2")
            chain.append(
                f"drawtext=fontfile={FONT}:text='{label}':x=4:y=4:fontsize=11:"
                f"fontcolor=yellow:box=1:boxcolor=black@0.8:boxborderw=3")
            r = subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t:.3f}",
                 "-i", s["src"], "-vf", ",".join(chain), "-frames:v", "1", dest],
                capture_output=True, text=True, errors="replace")
            if r.returncode != 0:
                print(f"    FAILED shot {i + 1} pan {p}\n{r.stderr[-400:]}", file=sys.stderr)
                return False
            tiles.append(dest)

    dest = os.path.join(social, f"{name}_pan.jpg")
    seq = os.path.join(tmp, "t%03d.png")
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-framerate", "1", "-i", seq,
         "-vf", f"tile={len(PANS)}x{len(job['shots'])}:margin=4:padding=4:color=0x181818",
         "-frames:v", "1", "-q:v", "3", dest], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"    FAILED tiling\n{r.stderr[-400:]}", file=sys.stderr)
        return False
    for f in tiles:
        os.remove(f)
    os.rmdir(tmp)
    print(f"  {os.path.relpath(dest, ROOT)}  "
          f"({len(job['shots'])} shots x {len(PANS)} pans)")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    return 0 if all(sheet(a) for a in sys.argv[1:]) else 1


if __name__ == "__main__":
    sys.exit(main())
