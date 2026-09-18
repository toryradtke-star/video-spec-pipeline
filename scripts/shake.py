"""Measure camera shake in a clip window, so shot choices are not a matter of opinion.

Estimates global frame-to-frame motion by phase correlation on downscaled greyscale
frames, then reports two numbers that mean different things:

  drift   mean per-frame displacement, in pixels of a 1920-wide frame.
          A deliberate push or lateral move scores high here. That is fine.
  shake   RMS of the *change* in displacement between frames — acceleration.
          A tripod move is smooth, so its acceleration is near zero however fast
          it travels. Handheld wobble changes direction constantly and scores high.
          This is the number that matters.

Rules of thumb on this footage, at 480-wide with sub-pixel fitting: under 0.30 is
a locked-off tripod, 0.30-0.80 is a steady handheld that passes, 0.80-1.40 is
loose, above 1.40 is visibly unsteady on a big screen.

    python scripts/shake.py "2G 01 B"                  whole clip, per 2s block
    python scripts/shake.py "2G 01 B" 5.0 3.0          one window: start, duration
    python scripts/shake.py --page custom-labels       every shot in a built cut
    python scripts/shake.py --page custom-labels:steady
    python scripts/shake.py --file out.mp4 22.5 4.5    a finished render
"""
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clips as clip_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 480 wide with sub-pixel peak fitting. The first version used 192 wide with
# integer peaks, which quantised to 10 full-frame pixels per frame — so a slow
# floaty drift measured 0.00 and was reported "locked off" while still looking
# unsteady. Anything below about 0.3 here is genuinely still.
W, H, FPS = 480, 270, 30
SCALE = 1920 / W          # report in full-frame pixels


def frames(src, start, dur):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
         "-vf", f"fps={FPS},scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    n = len(raw) // (W * H)
    if n < 3:
        return None
    return np.frombuffer(raw[:n * W * H], dtype=np.uint8).reshape(n, H, W).astype(np.float32)


def _sub(r, i, n):
    """Parabolic fit around a correlation peak, for sub-pixel precision."""
    a, b, c = r[(i - 1) % n], r[i], r[(i + 1) % n]
    d = a - 2 * b + c
    return 0.0 if d == 0 else np.clip(0.5 * (a - c) / d, -0.5, 0.5)


def shifts(f):
    """Per-frame (dy, dx) by phase correlation, windowed to kill edge effects."""
    win = np.outer(np.hanning(H), np.hanning(W))
    F = np.fft.rfft2(f * win)
    out = []
    for i in range(len(f) - 1):
        c = F[i] * np.conj(F[i + 1])
        mag = np.abs(c)
        mag[mag == 0] = 1e-9
        r = np.fft.irfft2(c / mag, s=(H, W))
        py, px = np.unravel_index(np.argmax(r), r.shape)
        # refine along each axis through the peak, then unwrap
        dy = py + _sub(r[:, px], py, H)
        dx = px + _sub(r[py, :], px, W)
        if dy > H / 2:
            dy -= H
        if dx > W / 2:
            dx -= W
        out.append((dy, dx))
    return np.array(out, dtype=np.float32)


def measure(src, start, dur):
    f = frames(src, start, dur)
    if f is None:
        return None
    s = shifts(f)
    drift = float(np.mean(np.hypot(s[:, 0], s[:, 1]))) * SCALE
    d = np.diff(s, axis=0)
    shake = float(np.sqrt(np.mean(d[:, 0] ** 2 + d[:, 1] ** 2))) * SCALE if len(d) else 0.0
    return drift, shake


def verdict(shake):
    return ("locked off" if shake < 0.30 else
            "steady" if shake < 0.80 else
            "loose" if shake < 1.40 else
            "SHAKY")


def report(label, src, start, dur):
    m = measure(src, start, dur)
    if not m:
        print(f"  {label:34} too short to measure")
        return None
    drift, shake = m
    print(f"  {label:34} {start:6.1f}+{dur:<4.1f} drift {drift:5.2f}  "
          f"shake {shake:5.2f}  {verdict(shake)}")
    return shake


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    if args[0] == "--file":
        # Measure a finished render. This is the only way to see whether
        # stabilisation worked, because it is applied at render time and so
        # never shows up in a measurement of the source clip.
        f = args[1]
        if len(args) >= 4:
            report(os.path.basename(f), f, float(args[2]), float(args[3]))
        else:
            print(f"\n{os.path.basename(f)}")
            t = 0.0
            while t + 2.0 <= 30.0:
                report("", f, t, 2.0)
                t += 2.0
        return 0

    if args[0] == "--page":
        slug, _, variant = args[1].partition(":")
        jobs = f"jobs-{variant}.json" if variant else "jobs.json"
        spec = json.load(open(os.path.join(ROOT, "pages", slug, jobs), encoding="utf-8"))
        print(f"\n{args[1]}")
        worst = []
        for i, s in enumerate(spec["jobs"][0]["shots"], 1):
            sh = report(f"{i}. {s['clip']}", s["src"], s["start"], s["dur"])
            if sh and sh >= 0.80:
                worst.append((s["clip"], s["start"], sh))
        if worst:
            print("\n  needs replacing:")
            for c, st, sh in sorted(worst, key=lambda x: -x[2]):
                print(f"    {c} @{st}  shake {sh:.2f}")
        else:
            print("\n  every shot is steady")
        return 0

    slate = args[0]
    src = clip_mod.resolve(slate)
    if len(args) >= 3:
        report(slate, src, float(args[1]), float(args[2]))
    else:
        total = clip_mod.duration(src)
        print(f"\n{slate}  ({total:.1f}s)")
        t = 0.0
        while t + 2.0 <= total:
            report(slate, src, t, 2.0)
            t += 2.0
    return 0


if __name__ == "__main__":
    sys.exit(main())
