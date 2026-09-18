"""QC a finished 9:16 social cut: contact sheet, loop seam, brightness profile.

    python scripts/qc_social.py example-product/loop [more ...]

Writes pages/<slug>/social/<name>_qc.jpg and prints two numbers that decide
whether the cut ships.

**Loop seam.** The first and last frames are compared, cropped to the footage
window. Cropping matters: the card, the type and the logo are identical in every
frame and make up two thirds of the picture, so an uncropped PSNR is enormous
however badly the footage jumps.

The number here is advisory, and **v1's 29 dB baseline does not apply.** That
figure came from a loop whose seam was a 0.6s crossfade, where the failure mode
was a ghost frame and 29 dB was the point at which it stopped showing. These cuts
hard-cut, so a ghost is not possible; the failure mode is the loop reading as a
jump to a different subject. `example-product/loop` measured 18.4 dB and
looks right — the same room, half a step of push-in — because the metric punishes
the drift a deliberate camera move causes. Under ~14 dB is worth a look; above
that, trust the sheet.

**Brightness.** The *step at each cut* between neighbouring shot means — that is
what flashes. A global min/max cannot tell it apart from a shot whose own content
darkens partway through, which is how `example-product/loop` was briefly reported as
flashing when its four shots sat inside 12 points of each other and one shot simply
moved into shadow on its own. Measured on the footage window only: unlike the 16:9
program there is no caption band over the picture to skew a bright subject sitting
low in frame. Level a cut with `level_social.py`.
"""
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import level_social as lvl
import render_social as rs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "pages")
FONT = config.FONT
COLS, THUMB, SAMPLE_FPS = 6, 300, 2
FPS = 30
JUMP_PSNR = 14.0        # below this the loop reads as a cut to a different subject
STEP_WARN = 15.0        # YAVG step at a cut that starts to read as a flash


def sh(args):
    return subprocess.run(args, capture_output=True, text=True, errors="replace")


def probe(src, entries, stream=True):
    sel = ["-select_streams", "v:0"] if stream else []
    out = sh(["ffprobe", "-v", "error"] + sel +
             ["-show_entries", entries, "-of", "csv=p=0", src]).stdout
    return out.strip()


def sheet(src, dest):
    vf = (f"fps={SAMPLE_FPS},"
          f"drawtext=fontfile={FONT}:text='%{{pts\\:hms}}':x=10:y=10:fontsize=30:"
          f"fontcolor=yellow:box=1:boxcolor=black@0.85:boxborderw=5,"
          f"scale={THUMB}:-2,tile={COLS}x4:margin=4:padding=4:color=0x111111")
    r = sh(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src,
            "-vf", vf, "-frames:v", "1", dest])
    return r.returncode == 0, r.stderr


def foot_crop(social, name):
    """The cut's own footage window, read off its jobs file.

    Hardcoding 1080x608 here would silently measure the wrong region on any cut
    that opted into a taller window, and the brightness profile would pick up the
    red card instead of the picture.
    """
    jobs = os.path.join(social, f"{name}_jobs.json")
    h, job = rs.FOOT_H_DEFAULT, {}
    if os.path.exists(jobs):
        with open(jobs, encoding="utf-8") as f:
            job = json.load(f)["jobs"][0]
        h = int(job.get("footage_h", h))
    if job.get("layout", "full") != "card":
        # Full screen: the picture is the frame. Measure above the bottom scrim,
        # which darkens the lower third by design.
        return f"crop={rs.W}:{rs.SCRIM_BOTTOM_Y}:0:0", rs.H
    y, _ = rs.geometry(h)
    return f"crop={rs.FOOT_W}:{h}:0:{y}", h


def frame(src, t, dest, foot):
    """One exact frame. -ss before -i is accurate here: it decodes and discards."""
    return (sh(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t:.4f}",
                "-i", src, "-vf", foot, "-frames:v", "1", dest]).returncode == 0
            and os.path.exists(dest))


def last_frame(src, dest, foot):
    """The final frame, by seeking from EOF and reversing the tail.

    Seeking to (nframes-1)/fps looks right and is not: it can land past the last
    frame's PTS, whereupon ffmpeg writes nothing and still exits 0. That is what
    reported `example-product/loop` as unmeasurable while its loop was in fact fine
    at 22 dB. Reversing a half-second tail asks for the last frame instead of
    calculating where it ought to be.
    """
    return (sh(["ffmpeg", "-nostdin", "-v", "error", "-y", "-sseof", "-0.5",
                "-i", src, "-vf", f"{foot},reverse", "-frames:v", "1",
                dest]).returncode == 0 and os.path.exists(dest))


def loop_psnr(src, nframes, tmp, foot):
    """PSNR between the footage in the first and last frames."""
    a, b = os.path.join(tmp, "_loop_a.png"), os.path.join(tmp, "_loop_b.png")
    if not (frame(src, 0.0, a, foot) and last_frame(src, b, foot)):
        return None
    r = sh(["ffmpeg", "-nostdin", "-v", "info", "-i", a, "-i", b,
            "-lavfi", "psnr", "-f", "null", "-"])
    for line in reversed(r.stderr.splitlines()):
        if "average:" in line:
            for tok in line.split():
                if tok.startswith("average:"):
                    val = tok.split(":", 1)[1]
                    try:
                        return float(val)
                    except ValueError:
                        return float("inf")   # identical frames report "inf"
    return None


def cut_steps(src, social, name, foot):
    """Per-shot means and the step at each cut, or None if the jobs file is gone."""
    jobs = os.path.join(social, f"{name}_jobs.json")
    if not os.path.exists(jobs):
        return None
    with open(jobs, encoding="utf-8") as f:
        job = json.load(f)["jobs"][0]
    return lvl.shot_levels(src, job, foot)


def qc(arg):
    slug, _, name = arg.partition("/")
    social = os.path.join(PAGES, slug, "social")
    src = os.path.join(social, f"{name}_9x16.mp4")
    if not os.path.exists(src):
        found = glob.glob(os.path.join(social, "*_9x16.mp4"))
        print(f"  no render at {os.path.relpath(src, ROOT)}"
              + (f" (have: {', '.join(os.path.basename(f) for f in found)})" if found else ""))
        return False

    w, h = probe(src, "stream=width,height").split(",")
    total = float(probe(src, "format=duration", stream=False))
    nframes = int(round(total * FPS))

    dest = os.path.join(social, f"{name}_qc.jpg")
    ok, err = sheet(src, dest)
    if not ok:
        print(f"  FAILED sheet for {arg}\n{err[-800:]}", file=sys.stderr)
        return False

    print(f"\n{slug}/{name}")
    print(f"  {w}x{h}  {total:.3f}s  {nframes} frames")
    if (w, h) != ("1080", "1920"):
        print(f"  !! not 1080x1920")

    foot, foot_h = foot_crop(social, name)
    print(f"  footage window {rs.FOOT_W}x{foot_h}"
          + ("" if foot_h == rs.FOOT_H_DEFAULT else "  (full screen, sides cropped)"))

    p = loop_psnr(src, nframes, social, foot)
    if p is None:
        print("  loop seam: could not measure")
    elif p == float("inf"):
        print("  loop seam: identical first and last frame — a perfect loop")
    else:
        print(f"  loop seam: {p:.1f} dB  "
              + ("continuous" if p >= JUMP_PSNR else
                 f"under {JUMP_PSNR:.0f} dB — may read as a jump, check the sheet"))

    lv = cut_steps(src, social, name, foot)
    if lv:
        means = [m for _, _, _, m in lv if m is not None]
        steps = [abs(b - a) for a, b in zip(means, means[1:])]
        # The wrap from the last shot back to the first is a cut too — it is the one
        # the loop plays.
        if len(means) > 1:
            steps.append(abs(means[0] - means[-1]))
        worst = max(steps) if steps else 0.0
        print(f"  brightness: " + " ".join(f"{m:.0f}" for m in means)
              + f" YAVG, worst step at a cut {worst:.0f}  "
              + ("ok" if worst <= STEP_WARN else "!! flashes"))

    for f in ("_loop_a.png", "_loop_b.png"):
        p2 = os.path.join(social, f)
        if os.path.exists(p2):
            os.remove(p2)
    print(f"  {os.path.relpath(dest, ROOT)}")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ok = all(qc(a) for a in sys.argv[1:])
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
