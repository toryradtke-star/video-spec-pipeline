"""Render a 9:16 social cut.

  1080x1920, 6-12s, no voiceover, music bed only, and it loops.

Two layouts. **`full`** is the default: the footage fills the frame and the type
sits on it over a gradient scrim. **`card`** puts the footage in a window on a
brand-red card with the type below it — kept because it is the only way to show a
frame whose sides cannot be cropped.

Full screen costs the sides of the frame: a 9:16 crop keeps ~32% of the width. What
makes it worth having anyway is resolution. The real-footage **originals are
4096x2160**, so a 9:16 crop is 1215x2160 and scaling it to 1080x1920 is a
*downscale* — full screen at native quality. `build_social.py` therefore reads the
original rather than the 2048x1080 proxy on this path. The AI clips have no
original: Flow delivered 1280x720, whose 9:16 crop is 405x720 and needs a 2.67x
upscale. Per-shot `pan` exists because a centre crop puts the decal off frame as
often as not.

Three things make this a separate path from render30.py rather than a flag on it:

  - **The frame is vertical**, and v1's note that vertical geometry does not
    transfer is still true.
  - **There is no end card**, because the logo is on screen for the whole cut. That
    is what lets the cut loop: sub-15s verticals are short enough to be rewatched,
    and a rewatch counts double.
  - **The bed does not fade** when the cut is the same length as the bed's loop.
    A fade at the seam is audible on the second pass round.

    python scripts/render_social.py pages/<slug>/social/<name>_jobs.json [outdir]

Everything geometry-independent is imported from render30 rather than copied —
in particular `segments`, which carries the cumulative ceil-snapped frame grid
that stopped captions landing a frame off the picture cuts.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import render30 as r30
from render30 import esc, frame_at, run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "_assets")
SCRIM_BOTTOM = os.path.join(ASSETS, "scrim_bottom.png")
SCRIM_TOP = os.path.join(ASSETS, "scrim_top.png")

W, H = 1080, 1920
FPS = 30
CRF = "18"
BRAND = config.BRAND
LOGO = r30.LOGO
FONT = r30.FONT                    # escaped drive colon: the path goes inside a filter string

CLAIM_SIZE, LINE_H = 76, 96
RULE_W, RULE_H = 260, 7
EYEBROW_SIZE = 40

# --- full-screen geometry ----------------------------------------------------
# Everything below the footage is bottom-anchored as one group, and the group ends
# at 1660 rather than at the frame edge: the bottom ~260px of a Reel or a Short is
# under the platform's own caption and buttons, and the right ~120px under its
# action rail. Nothing that has to be read goes there.
FULL_EYEBROW_Y = 140
FULL_BLOCK_BOTTOM = 1660
FULL_LOGO_W, FULL_LOGO_H = 500, 170     # 3157x1072 logo at 500 wide
FULL_RULE_GAP = 44
SCRIM_BOTTOM_Y = H - 880

# --- card geometry (the alternative layout) ----------------------------------
# 608 is the tallest a full 16:9 frame goes at 1080 wide, so nothing is cropped.
FOOT_W, FOOT_H_DEFAULT = 1080, 608
CARD_EYEBROW_Y = 190
CARD_RULE_GAP = 80
CARD_LOGO_W, CARD_LOGO_Y = 620, 1660
CARD_TYPE_BOTTOM = CARD_LOGO_Y - 40

BED_ALONE = 0.55                   # no voiceover on these, so the bed carries alone


# ---------------------------------------------------------------- footage fit

def fit_full(pan=0.0):
    """Scale to cover the whole frame, then crop 1080 wide at `pan`.

    `pan` is -1 (hard left) .. 0 (centre) .. +1 (hard right). A centre crop is only
    right when the subject is centred, which for a decal on a storefront or a van
    is the exception.
    """
    p = max(-1.0, min(1.0, float(pan)))
    # (iw-ow)/2 is the centred x; the pan slides it by the same amount either way,
    # so +-1 lands exactly on the frame edge and can never crop out of bounds.
    x = f"(iw-{W})/2+({p:.4f})*(iw-{W})/2"
    return (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:{x}:(ih-{H})/2")


def fit_card(foot_h):
    """Scale to cover the footage window, then centre-crop."""
    return (f"scale={FOOT_W}:{foot_h}:force_original_aspect_ratio=increase,"
            f"crop={FOOT_W}:{foot_h}:(iw-{FOOT_W})/2:(ih-{foot_h})/2")


def segments(shots, fits, extra_last=0.0):
    """render30.segments with a per-shot fit substituted.

    It resolves `fit` out of render30's globals at call time, so swapping the name
    there is enough. Reusing it rather than reimplementing it matters: it carries
    the cumulative ceil-snapped frame grid, the grade -> adjust -> stabilise
    ordering, and the tpad-then-trim guard. A second copy for a second aspect
    ratio would be a second copy of the bug it was written to fix.

    `fits` is one filter string per shot, because on the full-screen path each shot
    has its own pan.
    """
    saved = r30.fit
    seq = iter(fits)
    r30.fit = lambda: next(seq)
    try:
        return r30.segments(shots, extra_last)
    finally:
        r30.fit = saved


# ---------------------------------------------------------------------- type

def geometry(foot_h):
    """Card layout: (footage y, top of the type area) for a footage height."""
    foot_y = int(round(280 - (foot_h - FOOT_H_DEFAULT) / 2))
    return foot_y, foot_y + foot_h + 32


def layout_full(nlines):
    """(claim top, rule y) bottom-anchored above the logo."""
    logo_top = FULL_BLOCK_BOTTOM - FULL_LOGO_H
    rule_y = logo_top - FULL_RULE_GAP - RULE_H
    return rule_y - FULL_RULE_GAP - nlines * LINE_H, rule_y


def layout_card(nlines, type_top):
    """(claim top, rule y) centred between the footage and the logo."""
    group = nlines * LINE_H + CARD_RULE_GAP + RULE_H
    top = type_top + (CARD_TYPE_BOTTOM - type_top - group) // 2
    return top, top + nlines * LINE_H + CARD_RULE_GAP


def eyebrow(text, y, alpha):
    """The category label, on for the whole cut."""
    return (f"drawtext=fontfile='{FONT}':text='{esc(text.upper())}':"
            f"fontcolor=white@{alpha}:fontsize={EYEBROW_SIZE}:borderw=0:"
            f"x=(w-text_w)/2:y={y}")


def claim(lines, t0, t1, top, rule_y, rule_colour):
    """One claim: up to three lines of type plus the rule, gated to its window.

    One drawtext per line, not one drawtext with newlines: `esc` doubles
    backslashes, so an embedded `\\n` would reach ffmpeg as a literal.

    Gated on the frame index rather than on t, for the same reason render30's
    caption is — a boundary that falls on an exact frame is a float coin-toss for
    `between(t,...)`, and the claim would switch a frame after the picture cut.
    """
    on = f"between(n,{frame_at(t0)},{frame_at(t1) - 1})"
    parts = [
        f"drawtext=fontfile='{FONT}':text='{esc(ln.upper())}':"
        f"fontcolor=white:fontsize={CLAIM_SIZE}:borderw=0:"
        f"x=(w-text_w)/2:y={top + i * LINE_H}:enable='{on}'"
        for i, ln in enumerate(lines)
    ]
    parts.append(f"drawbox=x=(iw-{RULE_W})/2:y={rule_y}:w={RULE_W}:h={RULE_H}:"
                 f"color={rule_colour}:t=fill:enable='{on}'")
    return ",".join(parts)


# --------------------------------------------------------------------- audio

def bed(music_idx, total, seamless, gain=None):
    """Music bed, or silence.

    No fades when the bed is the cut's own length — the cut loops, and a fade at
    the seam is audible on the second pass. A bed that has to be trimmed to a
    shorter cut lands mid-phrase, so that one gets short edge fades instead: an
    audio dip at the seam is far less noticeable than a picture ghost.
    """
    if music_idx is None:
        return f"anullsrc=r=48000:cl=stereo,atrim=0:{total}[a]"
    vol = BED_ALONE if gain is None else gain
    fades = "" if seamless else (f"afade=t=in:st=0:d=0.25,"
                                 f"afade=t=out:st={total - 0.25:.3f}:d=0.25,")
    # apad before the fades so a bed a hair shorter than the cut cannot leave the
    # tail silent, and the out-fade always has material to act on.
    return (f"[{music_idx}:a]atrim=0:{total},apad=whole_dur={total},"
            f"{fades}volume={vol}[a]")


# -------------------------------------------------------------------- render

def render(job, dest, cwd=None):
    shots = [dict(s) for s in job["shots"]]
    total = job.get("body_dur") or sum(s["dur"] for s in shots)
    # Trim by frame count, not by time: `trim=0:8.888889` drops the part-frame and
    # leaves the picture 22ms shorter than the bed it has to loop with.
    frames = int(job.get("body_frames") or round(total * FPS))
    total = frames / FPS
    full = job.get("layout", "full") != "card"

    if full:
        fits = [fit_full(s.get("pan", 0.0)) for s in shots]
    else:
        foot_h = int(job.get("footage_h", FOOT_H_DEFAULT))
        foot_y, type_top = geometry(foot_h)
        fits = [fit_card(foot_h)] * len(shots)

    inputs, pre = segments(shots, fits, extra_last=0.5)
    n = len(shots)

    extra, music_idx = [], None
    if job.get("music") is not False:
        music_idx = n + len(extra)
        extra.append(job["music"] if isinstance(job.get("music"), str) else r30.MUSIC)
    logo_idx = n + len(extra)
    extra.append(LOGO)
    scrim_b_idx = scrim_t_idx = None
    if full:
        scrim_b_idx = n + len(extra)
        extra.append(SCRIM_BOTTOM)
        scrim_t_idx = n + len(extra)
        extra.append(SCRIM_TOP)

    # Pad the footage, overrun the backdrop, and trim the *composite* to the frame
    # count. Two separate off-by-ones live here and both cost a frame:
    # `color=d=8.9:r=30` yields 266 frames rather than the 267 that 8.9s at 30fps
    # implies, and `overlay` consumes a frame of its foreground without emitting one.
    # Either is enough to clip a frame off every 4- and 5-bar cut, which is a frame
    # of drift against a bed the cut is supposed to loop with. Trimming last, on
    # surplus material, makes the length exact by construction.
    stage = [pre,
             f"[cat]tpad=stop=-1:stop_mode=clone:stop_duration=1,setpts=PTS-STARTPTS[fg];",
             f"color=c={BRAND}:s={W}x{H}:d={total + 2}:r={FPS},setsar=1[bg];"]

    if full:
        # The footage already fills the frame, so the red only ever shows through if
        # something upstream fails — which is the point of compositing onto it.
        stage.append(f"[bg][fg]overlay=0:0:eof_action=endall[v0];")
        stage.append(f"[{scrim_t_idx}:v]null[st];[v0][st]overlay=0:0[v1];")
        stage.append(f"[{scrim_b_idx}:v]null[sb];[v1][sb]overlay=0:{SCRIM_BOTTOM_Y}[v2];")
        stage.append(f"[{logo_idx}:v]scale={FULL_LOGO_W}:-1[lg];")
        stage.append(f"[v2][lg]overlay=(W-w)/2:{FULL_BLOCK_BOTTOM - FULL_LOGO_H}[v3];")
        draw = [eyebrow(job["eyebrow"], FULL_EYEBROW_Y, "0.85")] if job.get("eyebrow") else []
        for lines, a, b in job["claims"]:
            top, rule_y = layout_full(len(lines))
            draw.append(claim(lines, a, b, top, rule_y, "white"))
    else:
        stage.append(f"[bg][fg]overlay=0:{foot_y}:eof_action=endall[v0];")
        stage.append(f"[{logo_idx}:v]scale={CARD_LOGO_W}:-1[lg];")
        stage.append(f"[v0][lg]overlay=(W-w)/2:{CARD_LOGO_Y}[v3];")
        draw = [eyebrow(job["eyebrow"], CARD_EYEBROW_Y, "0.75")] if job.get("eyebrow") else []
        for lines, a, b in job["claims"]:
            top, rule_y = layout_card(len(lines), type_top)
            draw.append(claim(lines, a, b, top, rule_y, "white"))

    chrome = "".join("," + d for d in draw)
    stage.append(f"[v3]trim=end_frame={frames},setpts=PTS-STARTPTS{chrome}[v];")

    fc = "".join(stage) + bed(music_idx, total, job.get("music_seamless", False),
                              job.get("music_gain"))

    cmd = (["ffmpeg", "-nostdin", "-v", "error", "-y"] + inputs +
           [a for path in extra for a in ("-i", path)] +
           ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-crf", CRF, "-preset", "slow", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest", "-movflags", "+faststart", dest])
    return run(cmd, os.path.basename(dest), cwd=cwd)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    here = os.path.dirname(os.path.abspath(sys.argv[1]))
    outdir = sys.argv[2] if len(sys.argv) > 2 else here
    os.makedirs(outdir, exist_ok=True)
    ok_all = True
    for job in spec["jobs"]:
        dest = os.path.join(outdir, job["out"])
        print(f"  {job['out']} ({job.get('layout', 'full')}, {len(job['shots'])} shots, "
              f"{job.get('body_dur')}s) ...", flush=True)
        # cwd is the social folder: vidstabtransform's `input=` only takes a relative path.
        ok = render(job, dest, cwd=job.get("cwd") or here)
        ok_all = ok_all and ok
        print(f"  {'OK  ' if ok else 'FAIL'} {job['out']}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
