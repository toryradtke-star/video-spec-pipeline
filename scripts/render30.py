"""Render a v2 30s narrated explainer for a product page.

  16:9, 1920x1080, captioned, brand end card, music bed, optional voiceover.

This is a separate path from render.py on purpose. render.py's `loop` kind is
silent, captionless and cross-dissolves a seam so it can autoplay forever;
its `social` kind is hardcoded to 1080x1920 with a three-beat caption map.
A v2 explainer is none of those: it plays once, it carries captions in a wide
frame, and it ends on a card.

    python scripts/render30.py pages/<slug>/jobs30.json [outdir]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import json
import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVL = config.OVERLAYS
LOGO = config.LOGO
MUSIC = config.MUSIC
FONT = config.font_drawtext()   # drawtext wants the drive colon escaped
BRAND = config.BRAND

W, H = 1920, 1080
FPS = 30
CRF = "18"
CARD = 3.0
BED_ALONE = 0.55
BED_UNDER_VO = 0.18

# Caption block, tuned for a wide frame. v1's vertical geometry does not transfer.
CAP_SIZE = 52
BAND_H = 150
BAND_Y = H - 275
TEXT_Y = H - 215
RULE_W, RULE_H = 260, 7
RULE_DY = 76


def run(cmd, label, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", cwd=cwd)
    if r.returncode != 0:
        print(f"  FAILED {label}\n{r.stderr[-1800:]}", file=sys.stderr)
        return False
    return True


def fit():
    """Scale to cover then centre-crop. No pan: 16:9 keeps the native framing."""
    return (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:(iw-{W})/2:(ih-{H})/2")


def esc(t):
    return (t.replace("\\", "\\\\").replace(":", "\\:")
             .replace("'", "\u2019").replace(",", "\\,").replace("%", "\\%"))


def cut_frames(shots):
    """Frame count per shot, taken off a cumulative ceil-snapped grid.

    The footage is 59.94fps and the output is 30, so `fps=30` on each shot
    lands on whatever count falls out of a 1.998:1 decimation. Concatenated,
    those roundings accumulate: the first finished cut ran its last four
    picture cuts 1-2 frames late while the captions — drawn on the finished
    timeline at exact timestamps — stayed on the grid. That put one frame of
    the outgoing shot under the incoming caption at 13.65s and 17.10s, which
    is what read as a glitch.

    Snapping the *cumulative* boundary instead of each duration means an error
    can never carry into the next shot. `ceil` matches how drawtext's enable=
    resolves a boundary (the first frame whose t >= t0), so a caption switch
    and a picture cut on the same timestamp land on the same frame.
    """
    out, cum, prev = [], 0.0, 0
    for s in shots:
        cum += s["dur"]
        end = frame_at(cum)
        out.append(end - prev)
        prev = end
    return out


def segments(shots, extra_last=0.0):
    """Decode, grade and conform each shot, then concat into one [cat] stream."""
    args, chains, labels = [], [], []
    frames = cut_frames(shots)
    for i, s in enumerate(shots):
        # Decode a little past the shot so trim=end_frame always has material.
        take = s["dur"] + 0.25 + (extra_last if i == len(shots) - 1 else 0)
        args += ["-ss", f"{s['start']:.3f}", "-t", f"{take:.3f}", "-i", s["src"]]
        grade = s.get("grade")
        pre = f"{grade}," if grade and grade != "null" else ""
        # Per-shot trim for continuity. grade.py measures each clip on its own and
        # cannot know what the shot cuts against, so matching neighbours is manual.
        adjust = s.get("adjust")
        post = f"{adjust}," if adjust else ""
        # Stabilise at native resolution, before fit() scales and crops — vidstab
        # needs the real frame to work out how far it can shift without exposing edges.
        stab = s.get("stab")
        mid = f"{stab}," if stab else ""
        # tpad then trim, so the count is exact even if the decode came up short
        # of the 0.25s guard. A cloned frame only ever appears on a shot whose
        # source genuinely runs out, which build30.py reports as an overrun.
        chains.append(f"[{i}:v]{pre}{post}{mid}{fit()},fps={FPS},"
                      f"tpad=stop=-1:stop_mode=clone:stop_duration=1,"
                      f"trim=end_frame={frames[i]},setsar=1,setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")
    if len(shots) == 1:
        chains.append(f"{labels[0]}null[cat]")
    else:
        chains.append(f"{''.join(labels)}concat=n={len(shots)}:v=1:a=0[cat]")
    return args, ";".join(chains) + ";"


def frame_at(t):
    """The first output frame whose start is at or after t."""
    return math.ceil(t * FPS - 1e-6)


def caption(text, t0, t1):
    # Gate on the frame index, not on t. A boundary that falls on an exact frame
    # (17.10s = frame 513) is a float coin-toss for `between(t,...)`: 513/30 is
    # not representable, the comparison came out just under, and the caption
    # switched a frame after the picture. Integer frames make the caption switch
    # and the picture cut the same frame by construction, and end the range at
    # f1-1 so consecutive captions cannot both be on for one frame.
    on = f"between(n,{frame_at(t0)},{frame_at(t1) - 1})"
    return (
        f"drawbox=x=0:y={BAND_Y}:w={W}:h={BAND_H}:color=black@0.42:t=fill:enable='{on}',"
        f"drawtext=fontfile='{FONT}':text='{esc(text.upper())}':"
        f"fontcolor=white:fontsize={CAP_SIZE}:borderw=0:"
        f"x=(w-text_w)/2:y={TEXT_Y}:enable='{on}',"
        f"drawbox=x=(iw-{RULE_W})/2:y={TEXT_Y + RULE_DY}:w={RULE_W}:h={RULE_H}:"
        f"color={BRAND}:t=fill:enable='{on}'"
    )


DEFAULT_CLOSING = config.CLOSING


def end_card(idx, title, closing):
    """Full-bleed brand red, logo, product name, rule, closing line."""
    return (
        f"color=c={BRAND}:s={W}x{H}:d={CARD}:r=30,setsar=1[cbg];"
        f"[{idx}:v]scale={int(W * 0.40)}:-1[lg];"
        f"[cbg][lg]overlay=(W-w)/2:(H-h)/2-170[c1];"
        # drawtext understands H; drawbox only understands ih.
        f"[c1]drawtext=fontfile='{FONT}':text='{esc(title)}':"
        f"fontcolor=white:fontsize=64:x=(w-text_w)/2:y=H/2+95,"
        f"drawbox=x=(iw-{RULE_W})/2:y=ih/2+190:w={RULE_W}:h={RULE_H}:color=white:t=fill,"
        f"drawtext=fontfile='{FONT}':text='{esc(closing)}':"
        f"fontcolor=white@0.82:fontsize=40:x=(w-text_w)/2:y=H/2+240[card];"
    )


def voice_files(job):
    """Voiceover inputs, as a list of (path, start_seconds).

    Two ways to supply a read. `voice` is one continuous file that starts at 0.
    `voice_lines` is one file per beat, each placed at its own timestamp — far
    easier to record, because six short lines to time beats one 27-second take.
    """
    if job.get("voice_lines"):
        return [(v["file"], float(v.get("at", 0.0))) for v in job["voice_lines"]]
    if job.get("voice"):
        return [(job["voice"], 0.0)]
    return []


def audio_graph(music_idx, voice_idx0, total, lines, gain=None):
    """Music bed and/or voiceover.

    The bed ducks automatically when a voiceover is present. Either side can be
    absent: `music: false` in design.json drops the bed, and a page with no
    recorded read just gets the bed. With neither, the track is silent rather
    than missing, so the file always has an audio stream.

    `gain` overrides the default bed level. Tracks differ in loudness by several
    dB, so one fixed number cannot suit every bed.
    """
    parts, mix = [], []

    if music_idx is not None:
        # apad first: a bed shorter than the video would otherwise set the mix
        # length via `duration=first` and clip the tail of the voiceover.
        parts.append(f"[{music_idx}:a]atrim=0:{total},apad=whole_dur={total},"
                     f"afade=t=in:st=0:d=0.6,"
                     f"afade=t=out:st={total - 1.4}:d=1.4,"
                     f"volume={gain if gain is not None else (BED_UNDER_VO if lines else BED_ALONE)}[m]")
        mix.append("[m]")

    if lines:
        labels = []
        for i, (_, at) in enumerate(lines):
            ms = int(round(at * 1000))
            parts.append(f"[{voice_idx0 + i}:a]adelay={ms}|{ms},volume=1.0[vo{i}]")
            labels.append(f"[vo{i}]")
        if len(labels) == 1:
            parts.append(f"{labels[0]}apad=whole_dur={total}[vo]")
        else:
            parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:"
                         f"dropout_transition=0[vomix]")
            parts.append(f"[vomix]apad=whole_dur={total}[vo]")
        mix.append("[vo]")

    if not mix:
        parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total}[a]")
    elif len(mix) == 1:
        parts.append(f"{mix[0]}anull[a]")
    else:
        parts.append(f"{''.join(mix)}amix=inputs=2:normalize=0:duration=first[a]")
    return ";".join(parts)


def render(job, dest, cwd=None):
    shots = [dict(s) for s in job["shots"]]
    body = job.get("body_dur") or sum(s["dur"] for s in shots)
    total = body + CARD
    caps = "".join("," + caption(t, a, b) for t, a, b in job["captions"])

    inputs, pre = segments(shots, extra_last=0.5)
    n = len(shots)
    lines = voice_files(job)

    # Inputs after the shots, in order. `music: false` omits the bed entirely,
    # so every index downstream has to be computed rather than assumed.
    extra, music_idx = [], None
    if job.get("music") is not False:
        music_idx = n + len(extra)
        extra.append(job["music"] if isinstance(job.get("music"), str) else MUSIC)
    logo_idx = n + len(extra)
    extra.append(LOGO)
    voice_idx0 = n + len(extra)
    extra += [path for path, _ in lines]

    fc = (
        pre +
        f"[cat]trim=0:{body},setpts=PTS-STARTPTS{caps}[main];" +
        end_card(logo_idx, job["title"], job.get("closing") or DEFAULT_CLOSING) +
        f"[main][card]concat=n=2:v=1:a=0[v];" +
        audio_graph(music_idx, voice_idx0, total, lines, job.get("music_gain"))
    )

    cmd = (["ffmpeg", "-nostdin", "-v", "error", "-y"] + inputs +
           [a for path in extra for a in ("-i", path)] +
           ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-crf", CRF, "-preset", "slow", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest", "-movflags", "+faststart", dest])
    return run(cmd, os.path.basename(dest), cwd=cwd)


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(sys.argv[1]))
    os.makedirs(outdir, exist_ok=True)
    ok_all = True
    for job in spec["jobs"]:
        dest = os.path.join(outdir, job["out"])
        print(f"  {job['out']} ({len(job['shots'])} shots + card) ...", flush=True)
        ok = render(job, dest, cwd=os.path.dirname(os.path.abspath(sys.argv[1])))
        ok_all = ok_all and ok
        print(f"  {'OK  ' if ok else 'FAIL'} {job['out']}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
