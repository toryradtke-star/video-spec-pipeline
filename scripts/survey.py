"""Visual index of every clip in the footage library, one labelled frame each.

The old catalog was cleared, so there is no written description of any clip.
This rebuilds the only thing that actually helps: sheets of every clip with its
slate code burned in, so you can find footage by looking instead of guessing.
Choosing a page's shots starts here, then goes to `clips.py strip <slate>` for
in and out points.

Finding the laptop-ordering footage (2E/2F/2G) and the box-opening footage
(2C/1C/1G) came out of reading these sheets. Neither was catalogued anywhere.

    python scripts/survey.py

Writes _strips/survey_0.jpg .. survey_N.jpg, 32 clips per sheet.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import clips as clip_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRIPS = os.path.join(ROOT, "_strips")
FONT = config.FONT
PER_SHEET, COLS, THUMB_W = 32, 4, 320
AT = 0.42          # sample this far into each clip: past slates, before the tail


def frames():
    """One labelled thumbnail per clip, in pool order. Returns list of paths."""
    tmp = os.path.join(STRIPS, "_survey_frames")
    os.makedirs(tmp, exist_ok=True)
    out = []
    for digit, pool in sorted(clip_mod.POOLS.items()):
        folder = os.path.join(clip_mod.PROXIES, pool)
        # A library need not carry every pool. Survey what is there and say
        # which are missing, rather than failing on the first absent one.
        if not os.path.isdir(folder):
            print(f"  pool {digit}: no folder at {folder} — skipped")
            continue
        for name in sorted(os.listdir(folder)):
            if "_proxy" not in name.lower() or name.lower().endswith(".xmp"):
                continue
            slate = os.path.splitext(name)[0].rsplit("_", 1)[0]
            src = os.path.join(folder, name)
            dest = os.path.join(tmp, f"{len(out):03d}_{slate.replace(' ', '_')}.png")
            if not os.path.exists(dest):
                t = clip_mod.duration(src) * AT
                vf = (f"scale={THUMB_W}:-2,"
                      f"drawtext=fontfile={FONT}:text='{slate}':x=5:y=5:fontsize=20:"
                      f"fontcolor=yellow:box=1:boxcolor=black@0.8:boxborderw=4")
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                                "-ss", f"{t:.2f}", "-i", src, "-vf", vf,
                                "-frames:v", "1", dest], check=True)
            out.append(dest)
    return out


def sheet(paths, dest):
    n = len(paths)
    args = []
    for p in paths:
        args += ["-i", p]
    layout = []
    for k in range(n):
        r, c = divmod(k, COLS)
        x = "0" if c == 0 else "+".join(f"w{j}" for j in range(c))
        y = "0" if r == 0 else "+".join(f"h{j * COLS}" for j in range(r))
        layout.append(f"{x}_{y}")
    fc = ("".join(f"[{i}:v]" for i in range(n)) +
          f"xstack=inputs={n}:layout={'|'.join(layout)}:fill=black[v]")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y"] + args +
                   ["-filter_complex", fc, "-map", "[v]", dest], check=True)


def main():
    os.makedirs(STRIPS, exist_ok=True)
    paths = frames()
    print(f"  {len(paths)} clips")
    for i in range(0, len(paths), PER_SHEET):
        chunk = paths[i:i + PER_SHEET]
        dest = os.path.join(STRIPS, f"survey_{i // PER_SHEET}.jpg")
        sheet(chunk, dest)
        print(f"  {os.path.relpath(dest, ROOT)}  ({len(chunk)} clips)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
