"""Measure each shot's brightness in a finished social cut and level them.

    python scripts/level_social.py example-product/loop            # measure
    python scripts/level_social.py example-product/loop --apply    # write it back

**Why this exists.** A social cut inherits its shots from built pages, and their
`adjust` values were trimmed for continuity *inside those pages*, against
different neighbours. Re-ordering the shots invalidates every one of them. The
first batch came out with spreads of 33-52 YAVG where the built pages sit inside
30, and a 50-point step flashes at the cut.

`grade.py` cannot help: it measures a clip alone and by definition cannot know
what a shot cuts against. So this measures the *delivery* file, where the grade,
the `adjust`, the scale and the crop have all already happened, and works
backwards.

**The arithmetic is exact.** `eq=brightness=b` shifts YAVG by `b * 255` — the
built pages' own notes confirm it to the point ("89.7 -> 105" at `brightness=0.060`,
and 0.060 * 255 = 15.3). So the correction for a shot measuring M against a
target T is `b_new = b_old + (T - M) / 255`.

`--apply` rewrites the `brightness=` term in the shot's `adjust` in the *spec*
file, leaving any `gamma=` alongside it untouched, and records what it did. Run
build + render + qc again afterwards.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render30 as r30
import render_social as rs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "pages")
FPS = 30
TARGET = 105.0          # the house figure the 16:9 program levels to
LIMIT = 0.25            # beyond this a correction is turning the picture grey
CLIP_HEADROOM = 0.04    # extra share of the frame a correction may push to black/white
SAMPLES = (0.3, 0.5, 0.7)


def yavg_at(src, t, foot):
    """Mean luma of the footage window at one timestamp, 0-255."""
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.4f}", "-i", src,
         "-vf", f"{foot},scale=1:1,format=gray", "-frames:v", "1",
         "-f", "rawvideo", "-"], capture_output=True).stdout
    return raw[0] if raw else None


def hist_at(src, t, foot):
    """256-bin luma histogram of the footage window at one timestamp."""
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.4f}", "-i", src,
         "-vf", f"{foot},format=gray", "-frames:v", "1",
         "-f", "rawvideo", "-"], capture_output=True).stdout
    if not raw:
        return None
    h = [0] * 256
    for b in raw:
        h[b] += 1
    return h


def clipped(h, delta):
    """(near-black share, near-white share) after shifting luma by `delta` bytes.

    `eq=brightness` is a pure offset, so the histogram of the corrected frame is
    the current one shifted — the effect of a candidate correction can be read off
    the render already on disk without rendering anything.
    """
    n = sum(h) or 1
    lo = sum(h[:max(0, 8 - delta)]) / n
    hi = sum(h[min(256, 248 - delta):]) / n
    return lo, hi


def guard(h, cur, new, headroom=CLIP_HEADROOM):
    """Back a correction off until it stops crushing blacks or blowing highlights.

    **Why this is needed.** Levelling by mean YAVG assumes the mean describes the
    exposure. It does not when a large blown-out area drives it: `4A 01 B` reads 133
    because a white press sheet fills half the frame, not because the shop is
    bright. Correcting it to 105 by offset took the near-black share of the frame
    from 17% to 27% and lost the press mechanism, the monitor and the whole
    background to solid black — a worse picture than the uncorrected one, arrived at
    by a metric that was satisfied.

    So the mean sets the target and the histogram sets the limit.
    """
    if h is None:
        return new, ""
    lo0, hi0 = clipped(h, 0)

    def cost(b):
        lo, hi = clipped(h, int(round((b - cur) * 255)))
        return max(lo - lo0, hi - hi0)

    if cost(new) <= headroom:
        return new, ""
    # Walk back from the full correction toward no correction at all, in twentieths.
    # Bounded and monotone: clipping only ever decreases as the offset shrinks, so
    # the first acceptable fraction is the largest one, and `cur` itself always
    # qualifies because it is what the frame already is.
    for k in range(19, -1, -1):
        trial = cur + (new - cur) * k / 20.0
        if cost(trial) <= headroom:
            return trial, (f"  held at {trial:+.3f} ({new:+.3f} would clip "
                           f"{cost(new) * 100:.0f}% more of the frame)")
    return cur, f"  held at {cur:+.3f} (any correction clips)"


def brightness_of(adjust):
    """The brightness term in an `adjust`, and a callable that rewrites it."""
    if not adjust:
        return 0.0, lambda b: f"eq=brightness={b:.3f}"
    m = re.search(r"brightness=(-?[\d.]+)", adjust)
    if m:
        cur = float(m.group(1))
        return cur, lambda b, a=adjust, s=m.span(1): a[:s[0]] + f"{b:.3f}" + a[s[1]:]
    # An eq with no brightness term (gamma or saturation only): append one so the
    # existing correction survives.
    if adjust.startswith("eq="):
        return 0.0, lambda b, a=adjust: f"{a}:brightness={b:.3f}"
    return 0.0, lambda b, a=adjust: f"{a},eq=brightness={b:.3f}"


def mid_of(job, i):
    """Timestamp at the middle of shot i in the finished cut."""
    frames = r30.cut_frames(job["shots"])
    return (sum(frames[:i]) + frames[i] / 2.0) / FPS


def shot_levels(src, job, foot):
    """[(index, clip, start, mean YAVG)] for each shot in a finished cut.

    Sampled inside each shot, on the same cumulative ceil-snapped grid
    render_social cut on, so a sample can never land on the wrong side of a
    boundary. Shared with qc_social, because what flashes at a cut is the *step
    between shot means* — a global min/max cannot tell that apart from a shot whose
    own content darkens partway through.
    """
    frames = r30.cut_frames(job["shots"])
    out, cum = [], 0
    for i, s in enumerate(job["shots"]):
        f0, f1 = cum, cum + frames[i]
        cum = f1
        vals = [v for v in (yavg_at(src, (f0 + (f1 - f0) * p) / FPS, foot)
                            for p in SAMPLES) if v is not None]
        out.append((i, s["clip"], s["start"],
                    sum(vals) / len(vals) if vals else None))
    return out


def level(arg, apply=False, target=TARGET):
    slug, _, name = arg.partition("/")
    social = os.path.join(PAGES, slug, "social")
    src = os.path.join(social, f"{name}_9x16.mp4")
    jobs_p = os.path.join(social, f"{name}_jobs.json")
    spec_p = os.path.join(social, f"{name}.json")
    for p in (src, jobs_p, spec_p):
        if not os.path.exists(p):
            print(f"  missing {os.path.relpath(p, ROOT)}")
            return False

    job = json.load(open(jobs_p, encoding="utf-8"))["jobs"][0]
    spec = json.load(open(spec_p, encoding="utf-8"))
    # On the full-screen layout the picture IS the frame, so there is no window to
    # crop to; on the card layout the red surround would dominate the reading.
    if job.get("layout", "full") == "card":
        foot_h = int(job.get("footage_h", rs.FOOT_H_DEFAULT))
        foot_y, _ = rs.geometry(foot_h)
        foot = f"crop={rs.FOOT_W}:{foot_h}:0:{foot_y}"
    else:
        # Measure above the bottom scrim: it darkens the lower third by design and
        # would read as the shot being dark.
        foot = f"crop={rs.W}:{rs.SCRIM_BOTTOM_Y}:0:0"

    print(f"\n{slug}/{name}  target {target:.0f} YAVG")
    print(f"  {'shot':6} {'clip':44} {'in':>6} {'YAVG':>6} {'now':>7} {'->':>8}")

    rows = []
    for i, clip, start, m in shot_levels(src, job, foot):
        s = job["shots"][i]
        if m is None:
            print(f"  {i + 1:<6} {clip[:44]:44} could not measure")
            continue
        cur, rewrite = brightness_of(s.get("adjust"))
        new = cur + (target - m) / 255.0
        flag = ""
        if abs(new) > LIMIT:
            new = LIMIT if new > 0 else -LIMIT
            flag = f"  clamped at {LIMIT}"
        # The mean sets the target; the histogram sets the limit.
        new, held = guard(hist_at(src, mid_of(job, i), foot), cur, new)
        flag = flag + held
        rows.append((i, m, cur, new, rewrite, flag))
        print(f"  {i + 1:<6} {s['clip'][:44]:44} {s['start']:6.2f} {m:6.1f} "
              f"{cur:+7.3f} {new:+8.3f}{flag}")

    if rows:
        before = [r[1] for r in rows]
        after = [r[1] + (r[3] - r[2]) * 255 for r in rows]
        print(f"  spread {max(before) - min(before):.0f} -> "
              f"{max(after) - min(after):.0f} YAVG")

    if not apply:
        print("  (measure only; pass --apply to write it back)")
        return True

    # Write the corrections into the spec's shots, in order. A shot the spec left to
    # inherit gets an explicit `adjust` of its own, which is the point: the social
    # cut's levels are its own, not the source page's.
    for i, m, cur, new, rewrite, _ in rows:
        sh = spec["shots"][i]
        sh["adjust"] = rewrite(new)
        sh["adjust_note"] = f"{m:.0f} -> {target:.0f} in this cut (was {cur:+.3f})"
    json.dump(spec, open(spec_p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"  wrote {len(rows)} adjust(s) into {os.path.relpath(spec_p, ROOT)}")
    print(f"  now: python scripts/build_social.py {arg} && "
          f"python scripts/render_social.py {os.path.relpath(jobs_p, ROOT)}")
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    apply = "--apply" in sys.argv
    tgt = TARGET
    for a in sys.argv[1:]:
        if a.startswith("--target="):
            tgt = float(a.split("=", 1)[1])
    ok = all(level(a, apply, tgt) for a in args)
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
