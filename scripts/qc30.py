"""Contact sheet of a finished 30s cut, one frame per second, timecoded.

This samples the *delivery* file, so what you see is what ships: graded, scaled,
captioned, card and all. Reading it left to right you should be able to name
every beat and read every caption. If you cannot, neither can a viewer.

    python scripts/qc30.py custom-labels [more-slugs ...]

Writes pages/<slug>/qc.jpg.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "pages")
FONT = config.FONT
COLS, THUMB = 6, 480


def qc(arg):
    """`slug`, or `slug:variant` for an alternative cut of the same page."""
    slug, _, variant = arg.partition(":")
    folder = os.path.join(PAGES, slug)
    import glob
    pat = f"{slug}_*s_{variant}.mp4" if variant else f"{slug}_*s.mp4"
    # A page may not run 30s — match on the slug and pick the newest render.
    found = [f for f in glob.glob(os.path.join(folder, pat))
             if variant or f.count("_") == slug.count("_") + 1]
    src = max(found, key=os.path.getmtime) if found else ""
    if not src:
        print(f"  no render for {arg} — run render30.py first")
        return False
    dest = os.path.join(folder, f"qc-{variant}.jpg" if variant else "qc.jpg")

    vf = (f"fps=1,"
          f"drawtext=fontfile={FONT}:text='%{{eif\\:t\\:d}}s':x=10:y=10:fontsize=38:"
          f"fontcolor=yellow:box=1:boxcolor=black@0.85:boxborderw=6,"
          f"scale={THUMB}:-2,tile={COLS}x5:margin=4:padding=4:color=0x111111")
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src,
                        "-vf", vf, "-frames:v", "1", dest],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(f"  FAILED {slug}\n{r.stderr[-800:]}", file=sys.stderr)
        return False
    print(f"  {os.path.relpath(dest, ROOT)}")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    return 0 if all(qc(s) for s in sys.argv[1:]) else 1


if __name__ == "__main__":
    sys.exit(main())
