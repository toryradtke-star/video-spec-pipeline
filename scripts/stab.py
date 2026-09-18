"""Pre-compute stabilisation data for any shot a design marks `"stabilize": true`.

Stabilising is a two-pass job: vidstabdetect measures the camera's wobble and
writes it to a .trf file, then vidstabtransform undoes it. Pass 1 has to happen
before the render, so it lives here.

Use it when a shot is the *right* shot but handheld — when no steady alternative
shows the same thing. Replacing the shot is always the better fix if one exists,
because stabilising costs a slight crop: the frame has to zoom in a little to
hide the edges it shifts away from.

The .trf must be measured on exactly the window the render will use. Change a
shot's start or duration and its .trf is stale, so re-run this.

    python scripts/stab.py custom-labels
    python scripts/stab.py custom-labels:steady        a design variant

Writes pages/<slug>/_stab/*.trf.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clips as clip_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "pages")
SHAKINESS, ACCURACY = 8, 15


def trf_name(slate, start, dur):
    # A page asset arrives as a relative path ("Shots/foo.mp4"); flatten it so the
    # .trf is a legal filename, and drop the extension so it does not read as one.
    stem = os.path.splitext(os.path.basename(slate))[0]
    return f"{stem.replace(' ', '')}_{start:g}_{dur:g}.trf"


def resolve(slate, folder):
    """Slate code -> proxy path, or a page-relative asset path -> itself.

    Same rule as build30.check(): anything carrying an extension or a separator is
    an asset kept beside the page, not a pool clip.
    """
    if os.path.splitext(slate)[1] or "/" in slate or "\\" in slate:
        return slate if os.path.isabs(slate) else os.path.join(folder, slate)
    return clip_mod.resolve(slate)


def detect(src, start, dur, outdir, fname):
    """Pass 1, on exactly the window the render will trim to.

    `result` is a bare filename with ffmpeg run from outdir. An absolute Windows
    path would put a drive-letter colon inside the filter arguments, where it
    reads as an option separator — and ffmpeg reports that as a misleading
    "Error opening output file", nowhere near the real cause.
    """
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y",
         "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
         "-vf", f"vidstabdetect=shakiness={SHAKINESS}:accuracy={ACCURACY}:result={fname}",
         "-f", "null", "-"],
        cwd=outdir, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(f"    FAILED\n{r.stderr[-600:]}", file=sys.stderr)
        return False
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    slug, _, variant = sys.argv[1].partition(":")
    folder = os.path.join(PAGES, slug)
    name = f"design-{variant}.json" if variant else "design.json"
    design = json.load(open(os.path.join(folder, name), encoding="utf-8"))

    outdir = os.path.join(folder, "_stab")
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for b in design["beats"]:
        for s in b["shots"]:
            if not s.get("stabilize"):
                continue
            slate, start, dur = s["clip"], s["start"], s["dur"]
            fname = trf_name(slate, start, dur)
            dest = os.path.join(outdir, fname)
            print(f"  {b['name']}: {slate} @{start} for {dur}s")
            if detect(resolve(slate, folder), start, dur, outdir, fname):
                print(f"    {os.path.relpath(dest, ROOT)}")
                n += 1
    print(f"\n  {n} shot(s) measured" if n else "\n  nothing marked for stabilising")
    return 0


if __name__ == "__main__":
    sys.exit(main())
