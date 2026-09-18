"""Measure a log clip's real signal range and derive a per-clip grade.

The shoot proxies are flat CineForm: black sits around code 30 and white around
120 out of 255, and the four locations sit at different levels, so one fixed
curve does not serve them all. This samples the clip, finds its true black and
white points by percentile, and builds the ffmpeg chain that maps them to full
range.

Two things this gets right that a hand-written filter usually gets wrong:

* Measurement happens in the same 8-bit RGB domain the correction is applied in.
  Measuring 10-bit YUV code values and feeding them to colorlevels silently
  crushes the image, because the two use different scales.
* The chain is prefixed with format=rgb24. colorlevels on a high-bit-depth input
  produces a near-black frame in this ffmpeg build; forcing 8-bit RGB first is
  what makes it behave.
"""
import json
import subprocess
import sys

SAMPLES = 6
GRID = "160:90"           # enough pixels for stable percentiles, cheap to decode

BLACK_PCT, WHITE_PCT = 0.01, 0.99
BLACK_MARGIN = 4          # codes of headroom so shadows do not crush solid
WHITE_MARGIN = 4
TARGET_CHROMA = 22.0      # mean (max-min) RGB spread that reads natural after the stretch
WB_STRENGTH = 1.00        # full per-channel neutralisation; the stretch alone leaves a cast
SAT_MIN, SAT_MAX = 1.0, 1.45   # above ~1.5 sunlit walls go yellow


def sample(path, t):
    """Return (per-channel sorted bytes, mean RGB spread) for one frame."""
    base = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1"]
    rgb = subprocess.run(base + ["-vf", f"format=rgb24,scale={GRID}",
                                 "-f", "rawvideo", "-"], capture_output=True).stdout
    if not rgb:
        return None, None
    chans = [rgb[0::3], rgb[1::3], rgb[2::3]]
    spread = 0
    for r, g, b in zip(*chans):
        spread += max(r, g, b) - min(r, g, b)
    return [sorted(c) for c in chans], spread / len(chans[0])


def measure(path, duration):
    """Per-channel black/white points. Measuring R, G and B separately means the
    stretch also neutralises the colour cast, instead of amplifying it."""
    per = [{"black": [], "white": [], "mid": []} for _ in range(3)]
    chroma = []
    for i in range(SAMPLES):
        chans, spread = sample(path, duration * (i + 0.5) / SAMPLES)
        if not chans:
            continue
        for ci, c in enumerate(chans):
            n = len(c)
            per[ci]["black"].append(c[int(BLACK_PCT * (n - 1))])
            per[ci]["white"].append(c[int(WHITE_PCT * (n - 1))])
            per[ci]["mid"].append(c[n // 2])
        chroma.append(spread)
    if not chroma:
        return None
    med = lambda xs: sorted(xs)[len(xs) // 2]
    return {"ch": [{k: med(v) for k, v in p.items()} for p in per],
            "chroma": sum(chroma) / len(chroma), "samples": len(chroma)}


def build(st):
    ch = st["ch"]
    # Neutral reference: what the levels would be with no white balance at all.
    n_lo = sum(c["black"] for c in ch) / 3.0
    n_hi = sum(c["white"] for c in ch) / 3.0

    los, his = [], []
    for c in ch:
        # Blend each channel toward its own point by WB_STRENGTH, so a genuinely
        # warm scene stays warm rather than being forced grey.
        lo = n_lo + (c["black"] - n_lo) * WB_STRENGTH
        hi = n_hi + (c["white"] - n_hi) * WB_STRENGTH
        los.append(max(0, lo - BLACK_MARGIN) / 255.0)
        his.append(min(255, hi + WHITE_MARGIN) / 255.0)

    if min(h - l for l, h in zip(los, his)) < 0.08:   # too flat to be real
        los, his = [0.0] * 3, [1.0] * 3

    sat = TARGET_CHROMA / st["chroma"] if st["chroma"] > 1 else 1.0
    sat = round(min(SAT_MAX, max(SAT_MIN, sat)), 3)

    mid = sum(c["mid"] for c in ch) / 3.0 / 255.0
    lo_m, hi_m = sum(los) / 3, sum(his) / 3
    mid_out = (mid - lo_m) / max(1e-6, hi_m - lo_m)
    gamma = round(min(1.20, max(0.80, (0.45 / mid_out) ** 0.5)), 3) if mid_out > 0.02 else 1.0

    f = (f"format=rgb24,"
         f"colorlevels=rimin={los[0]:.4f}:gimin={los[1]:.4f}:bimin={los[2]:.4f}"
         f":rimax={his[0]:.4f}:gimax={his[1]:.4f}:bimax={his[2]:.4f},"
         f"eq=saturation={sat}:gamma={gamma}")
    return f, {"black_in": [round(x, 4) for x in los],
               "white_in": [round(x, 4) for x in his],
               "saturation": sat, "gamma": gamma, "measured": st}


def grade_for(path, duration):
    st = measure(path, duration)
    if not st:
        return "null", {"error": "measurement failed"}
    return build(st)


if __name__ == "__main__":
    f, params = grade_for(sys.argv[1], float(sys.argv[2]))
    print(json.dumps({"filter": f, **params}, indent=2))
