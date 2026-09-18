"""Resolve, grade and preview shoot clips straight from the proxy folders.

The catalog was cleared, so nothing here depends on manifest.json. A slate code
resolves to a path by convention, duration comes from ffprobe, and the grade is
measured once by grade.py and cached next to the pages.

    python scripts/clips.py grade "1K 02 A" "4D 04 B"     # measure + cache
    python scripts/clips.py strip "1K 02 A"               # contact strip to _strips/

Both are idempotent; grades are only measured the first time a clip is seen.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grade as grade_mod
import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXIES = config.PROXIES
GRADES = os.path.join(ROOT, "pages", "_grades.json")
STRIPS = os.path.join(ROOT, "_strips")
FONT = config.FONT

# leading slate digit -> proxy folder
POOLS = config.POOLS


def resolve(slate):
    """'1K 02 A' -> absolute proxy path. Matches case-insensitively on the stem."""
    pool = slate.strip()[:1]
    if pool not in POOLS:
        raise SystemExit(
            f"{slate!r}: {pool!r} is not a pool. Known pools: {', '.join(sorted(POOLS))}. "
            f"Set them in scripts/config.py."
        )
    folder = os.path.join(PROXIES, POOLS[pool])
    if not os.path.isdir(folder):
        raise SystemExit(
            f"no footage folder at {folder}\n"
            f"Point VSP_PROXIES at your footage library, or edit POOLS in scripts/config.py."
        )
    want = slate.strip().lower()
    for name in os.listdir(folder):
        stem = os.path.splitext(name)[0].lower()
        if stem.startswith(want) and "_proxy" in stem and not name.lower().endswith(".xmp"):
            return os.path.join(folder, name)
    raise SystemExit(f"no proxy found for {slate!r} in {folder}")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return float(out.strip())


def load_grades():
    if os.path.exists(GRADES):
        with open(GRADES, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_grades(cache):
    os.makedirs(os.path.dirname(GRADES), exist_ok=True)
    with open(GRADES, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
        f.write("\n")


def grade_of(slate, cache):
    """Measured grade string for a clip. 4L is already contrasty and stays ungraded."""
    if slate in cache:
        return cache[slate]["filter"]
    path = resolve(slate)
    if path.lower().endswith(".mxf"):
        cache[slate] = {"filter": None, "path": path, "note": "already contrasty; not log"}
        return None
    filt, params = grade_mod.grade_for(path, duration(path))
    cache[slate] = {"filter": filt, "path": path,
                    "saturation": params.get("saturation"), "gamma": params.get("gamma")}
    return filt


def strip(slate, cache):
    """Dense graded contact strip with burned-in timecode, for choosing in/out."""
    os.makedirs(STRIPS, exist_ok=True)
    path = resolve(slate)
    dur = duration(path)
    every = max(1.0, round(dur / 40))
    cols = 8
    rows = -(-int(dur / every) // cols)

    chain = []
    filt = grade_of(slate, cache)
    if filt:
        chain.append(filt)
    chain += [
        f"fps=1/{every}", "scale=300:-2",
        (f"drawtext=fontfile={FONT}:text='%{{pts\\:hms}}':x=8:y=8:fontsize=22:fontcolor=white"
         f":box=1:boxcolor=black@0.65:boxborderw=6"),
        f"tile={cols}x{rows}:margin=4:padding=4:color=0x111111",
    ]
    out = os.path.join(STRIPS, slate.replace(" ", "_") + ".jpg")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", path,
                    "-vf", ",".join(chain), "-frames:v", "1", "-q:v", "4", out], check=True)
    print(f"  {slate:<10} {dur:6.1f}s  every {every:.0f}s  -> {os.path.relpath(out, ROOT)}")


def main():
    cmd, slates = sys.argv[1], sys.argv[2:]
    cache = load_grades()
    for s in slates:
        if cmd == "grade":
            grade_of(s, cache)
            print(f"  {s:<10} {resolve(s)}")
        elif cmd == "strip":
            strip(s, cache)
        else:
            raise SystemExit("commands: grade | strip")
    save_grades(cache)
    print(f"\n{len(cache)} clips cached in {os.path.relpath(GRADES, ROOT)}")


# --- 4K originals ------------------------------------------------------------
# The proxies are 2048x1080 and the originals 4096x2160, both 10-bit 422 with
# identical luma (verified 2026-08-28 at three timestamps on 4A 01 B), so a grade
# measured on the proxy applies unchanged to the original.
#
# This matters only for the full-screen social cuts. A 9:16 crop keeps ~32% of the
# width: 608x1080 off a proxy needs a 1.78x upscale, while 1215x2160 off the
# original is a downscale. Nothing else in the program reads the originals.
ORIGINALS = config.ORIGINALS
ORIGIN_DIRS = config.ORIGIN_DIRS


def original(slate):
    """'1K 02 A' -> the 4K .MXF path, or None if there is no original.

    The AI-generated clips kept beside the pages have no original: Flow delivered
    them at 1280x720 and that is all there is.
    """
    folder = os.path.join(ORIGINALS, ORIGIN_DIRS.get(slate.strip()[0], ""))
    if not os.path.isdir(folder):
        return None
    want = slate.strip().lower()
    for name in os.listdir(folder):
        stem, ext = os.path.splitext(name)
        if ext.lower() == ".mxf" and stem.lower() == want:
            return os.path.join(folder, name)
    return None


if __name__ == "__main__":
    main()
