"""Stabilisation pass 1 for a social cut, measured on the source the cut actually reads.

    python scripts/stab_social.py example-product/loop

Writes pages/<slug>/social/_stab/*.trf.

**Why this is not just `stab.py`.** A .trf holds transforms in *pixels*, so it is
keyed to the resolution it was measured at as well as to the window. `stab.py`
measures the 2048x1080 proxy, which is what the 16:9 page videos render from. A
full-screen social cut renders from the 4096x2160 original instead — so the page's
.trf describes shifts half the size the frame needs, and `vidstabtransform` would
quietly apply half a correction. Nothing errors; the shot just stays shaky.

So a full-screen cut measures its own. Run this after `build_social.py` (which
resolves each shot to its real source) and before `render_social.py`.

Card-layout cuts read the proxy like the page videos do, and `build_social.py`
copies the page's .trf for those — they do not need this.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clips as clip_mod
import stab as stab_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "pages")


def run(arg):
    slug, _, name = arg.partition("/")
    social = os.path.join(PAGES, slug, "social")
    jobs_p = os.path.join(social, f"{name}_jobs.json")
    if not os.path.exists(jobs_p):
        print(f"  no {os.path.relpath(jobs_p, ROOT)} — run build_social.py first")
        return False
    job = json.load(open(jobs_p, encoding="utf-8"))["jobs"][0]

    outdir = os.path.join(social, "_stab")
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for s in job["shots"]:
        if not s.get("stab") and not s.get("stabilize"):
            continue
        fname = stab_mod.trf_name(s["clip"], s["start"], s["dur"])
        w, h = probe_size(s["src"])
        print(f"  {s['clip']} @{s['start']} for {s['dur']}s  ({w}x{h}) ...", flush=True)
        if stab_mod.detect(s["src"], s["start"], s["dur"], outdir, fname):
            print(f"    {os.path.relpath(os.path.join(outdir, fname), ROOT)}")
            n += 1
    print(f"\n  {n} shot(s) measured" if n else "\n  nothing marked for stabilising")
    return True


def probe_size(path):
    import subprocess
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0",
                          path], capture_output=True, text=True).stdout.strip()
    return out.split(",") if "," in out else ("?", "?")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    return 0 if all(run(a) for a in sys.argv[1:]) else 1


if __name__ == "__main__":
    sys.exit(main())
