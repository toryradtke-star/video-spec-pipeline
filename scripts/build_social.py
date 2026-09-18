"""Turn a social spec into a render spec, and check it before it renders.

A social cut is authored as ~15 lines because it inherits its shots from pages
that are already built. `"from": "example-product:Payoff:0"` pulls that page's clip,
in-point, brightness `adjust` and stabilisation verbatim — windows that have
already been measured for shake, matched to ~105 YAVG and screened for brand
marks. Re-picking them by hand would be throwing that away.

    python scripts/build_social.py example-product/loop [more ...]

Reads pages/<slug>/social/<name>.json, writes <name>_jobs.json beside it.

The checks are the point. Each one is a mistake this program has already made,
or a property the cut silently loses without it:

  - a duration off the 108 BPM bar grid, which puts the bed's loop out of phase
  - an in-point plus duration that runs off the end of the clip
  - a claim line too wide for the card, or a claim of more than three lines
  - a stale .trf: it is keyed to the window, so a changed duration invalidates it
  - a cut that does not loop, when it says it should
"""
import json
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import clips as clip_mod
import stab as stab_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "pages")
FONT_FILE = config.FONT

# The licensed bed is 108.00 BPM exactly: 4 beats to the bar, 2.222222s a bar.
# The pack's own loops confirm it — loop1 is 11.111125s, which is 5 bars.
BAR = 60.0 / 108.0 * 4
BARS_OK = (3, 4, 5)                # 6.67s, 8.89s, 11.11s
FPS = 30

# A bar is 66.667 frames, so only a multiple of 3 bars lands on a whole frame.
# The cut is snapped to whole frames and the bed follows it, because the
# alternative is worse: trimming the picture by time drops the part-frame and
# leaves the video 22ms shorter than the bed it is supposed to loop with. 11ms
# off the musical grid across one loop is a 0.1% tempo error and inaudible.
TOL = 0.002
ABSORB = 0.05                      # residual the closing shot may soak up (frames, not seconds)

CLAIM_SIZE = 76
MAX_LINES = 3
MAX_TEXT_W = 940                   # 1080 less a 70px margin each side
WIDTH_MARGIN = 1.04                # PIL and drawtext pick the same variable-font
                                   # instance but not to the pixel


def text_width(s, size=CLAIM_SIZE):
    """Rendered width of a claim line, or None if it cannot be measured."""
    try:
        from PIL import ImageFont
        return ImageFont.truetype(FONT_FILE, size).getlength(s.upper())
    except Exception:
        return None


def load_design(page):
    """A built page's design.json, and its folder."""
    folder = os.path.join(PAGES, page)
    with open(os.path.join(folder, "design.json"), encoding="utf-8") as f:
        return json.load(f), folder


def find_shot(design, beat_name, idx):
    for b in design["beats"]:
        if b["name"].lower() == beat_name.lower():
            return b["shots"][int(idx)]
    raise KeyError(beat_name)


def inherit(ref, cache, problems):
    """Resolve "page:Beat:idx" into a shot dict plus the folder it came from.

    Everything measured travels with it. `dur` comes along too but is routinely
    overridden — a social cut is paced differently from a 25s explainer.
    """
    page, beat, idx = ref.split(":")
    design, folder = load_design(page)
    src = find_shot(design, beat, idx)
    return dict(src), page, folder


def resolve_src(clip, folder, cache, problems, label, prefer_original=False):
    """Clip reference -> (path, grade, note). Mirrors build30's two kinds of source.

    A slate code resolves into the proxy pools and gets a measured grade. Anything
    with a path or an extension is an asset kept beside its page — an AI clip or a
    screen capture — already clean sRGB, and must not be graded like camera footage.

    `prefer_original` reads the 4096x2160 .MXF instead of the 2048x1080 proxy. Only
    the full-screen layout asks for it, and only because a 9:16 crop keeps ~32% of
    the width: off the proxy that is 608x1080 and needs a 1.78x upscale, off the
    original it is 1215x2160 and is a downscale. The grade is unchanged either way —
    both are 10-bit 422 off the same camera with identical luma.
    """
    asset = bool(os.path.splitext(clip)[1]) or "/" in clip or "\\" in clip
    if asset:
        path = clip if os.path.isabs(clip) else os.path.join(folder, clip)
        if not os.path.exists(path):
            problems.append(f"{label}: {clip} not found beside its page")
            return None, None, ""
        return path, None, "720p AI clip, no original"
    try:
        grade = clip_mod.grade_of(clip, cache)
        if prefer_original:
            orig = clip_mod.original(clip)
            if orig:
                return orig, grade, "4K original"
        return clip_mod.resolve(clip), grade, "2048x1080 proxy"
    except SystemExit as e:
        problems.append(f"{label}: {e}")
        return None, None, ""


def build(arg):
    slug, _, name = arg.partition("/")
    if not name:
        print(f"  need <slug>/<name>, got {arg!r}")
        return False
    social = os.path.join(PAGES, slug, "social")
    spec_path = os.path.join(social, f"{name}.json")
    if not os.path.exists(spec_path):
        print(f"  no spec at {os.path.relpath(spec_path, ROOT)}")
        return False
    spec = json.load(open(spec_path, encoding="utf-8"))
    cache = clip_mod.load_grades()
    problems, notes = [], []

    full = spec.get("layout", "full") != "card"
    bars = int(spec.get("bars", 3))
    if bars not in BARS_OK:
        problems.append(f"bars={bars}; use one of {BARS_OK} so the bed stays in phase")
    total_frames = int(round(bars * BAR * FPS))
    total = total_frames / FPS

    # --- shots ---------------------------------------------------------------
    raw = spec["shots"]
    free = [s for s in raw if s.get("dur") is None]
    fixed = sum(s["dur"] for s in raw if s.get("dur") is not None)
    share = (total - fixed) / len(free) if free else 0.0
    if free and share <= 0:
        problems.append(f"fixed shots already fill {fixed:.3f}s of {total:.3f}s, "
                        f"nothing left for the {len(free)} without a dur")

    shots, trfs = [], []
    for i, s in enumerate(raw):
        label = f"shot {i + 1}"
        if s.get("from"):
            base, page, folder = inherit(s["from"], cache, problems)
            label = f"shot {i + 1} ({s['from']})"
        else:
            base, page, folder = dict(s), slug, os.path.join(PAGES, slug)
        clip = s.get("clip", base.get("clip"))
        start = float(s.get("start", base.get("start", 0.0)))
        dur = s["dur"] if s.get("dur") is not None else round(share, 3)

        path, grade, srcnote = resolve_src(clip, folder, cache, problems, label,
                                           prefer_original=full)
        if path is None:
            continue
        clip_len = clip_mod.duration(path)
        if start + dur > clip_len + TOL:
            problems.append(f"{label}: {clip} wants {start}+{dur}={start + dur:.2f}s "
                            f"but the clip is only {clip_len:.2f}s")

        shot = {"clip": clip, "src": path, "start": start, "dur": dur, "grade": grade}
        adjust = s.get("adjust", base.get("adjust"))
        if adjust:
            shot["adjust"] = adjust
        # A centre crop puts the decal off frame as often as not, so a full-screen
        # shot usually needs a pan. It is never inherited: the source page framed
        # for 16:9 and had no reason to record one.
        if full and s.get("pan"):
            shot["pan"] = float(s["pan"])

        if s.get("stabilize", base.get("stabilize")):
            # The .trf is keyed to the window AND to the resolution, because its
            # transforms are in pixels. A card cut reads the same proxy the page did,
            # so the page's .trf is valid and gets copied in. A full-screen cut reads
            # the 4K original, where those shifts would be half the size the frame
            # needs — vidstabtransform applies half a correction and reports nothing.
            # So the full path measures its own, in social/_stab/.
            src_dur = base.get("dur")
            trf_name = stab_mod.trf_name(clip, start, dur)
            local_trf = os.path.join(social, "_stab", trf_name)
            src_trf = os.path.join(folder, "_stab", trf_name)
            if full:
                if not os.path.exists(local_trf):
                    problems.append(
                        f"{label}: marked stabilize and this is a full-screen cut, so it "
                        f"needs its own .trf measured on {os.path.basename(path)} — run: "
                        f"python scripts/stab_social.py {arg}   (build again first if the "
                        f"jobs file is stale)")
                    trf_ok = False
                else:
                    trf_ok = True
            elif not os.path.exists(src_trf):
                problems.append(
                    f"{label}: marked stabilize but no .trf for {start}+{dur}"
                    + (f" (the source page's is {start}+{src_dur}) — either keep dur at "
                       f"{src_dur} or run: python scripts/stab.py {page}"
                       if src_dur is not None and abs(src_dur - dur) > TOL
                       else f" — run: python scripts/stab.py {page}"))
                trf_ok = False
            else:
                trfs.append(src_trf)
                trf_ok = True
            if trf_ok:
                rel = f"_stab/{trf_name}"
                sm = int(s.get("stab_smoothing", base.get("stab_smoothing", 30)))
                shot["stab"] = (f"vidstabtransform=input={rel}"
                                f":smoothing={sm}:optzoom=1:interpol=bicubic")
            else:
                # Record the intent so stab_social.py can find the shot on the next pass.
                shot["stabilize"] = True
        shots.append(shot)
        notes.append((label, clip, start, dur, srcnote, shot.get("pan", 0.0)))

    # The frame-snapped total is not a round number, and the bar arithmetic an author
    # does by hand lands on 8.889 rather than 8.900. A residual under ABSORB is folded
    # into the closing shot — which on these cuts is the short return to the opening
    # image, the one place a few frames either way changes nothing. Anything larger is
    # a real authoring error and still fails.
    span = round(sum(s["dur"] for s in shots), 3)
    resid = total - span
    if shots and 0 < abs(resid) <= ABSORB:
        shots[-1]["dur"] = round(shots[-1]["dur"] + resid, 4)
        notes[-1] = notes[-1][:3] + (shots[-1]["dur"],) + notes[-1][4:]
        print(f"  absorbed {resid * 1000:+.0f}ms into the closing shot")
        span = round(sum(s["dur"] for s in shots), 3)
    if abs(span - total) > 0.01:
        problems.append(f"shots sum to {span}s, not {total:.3f}s ({bars} bars)")

    # --- loop ----------------------------------------------------------------
    # v1's rule, written down after the seam ghosted: a loop must end on the same
    # clip and moment it opens on. Two ways to satisfy it, and PSNR decides which
    # a given clip prefers:
    #   "repeat" — the closing shot is the opening window again. The last frame is
    #              the window's end, not its start, so it depends on the move being
    #              slow. This is what v1's rule says literally.
    #   "wrap"   — the closing shot ends exactly where the opening shot begins, so
    #              looping is continuous in the source. Rigorous, but it needs
    #              headroom before the opening in-point, which most of these 8s
    #              clips do not have.
    loop = spec.get("loop", "repeat")
    if loop and len(shots) >= 2:
        a, z = shots[0], shots[-1]
        if a["clip"] != z["clip"]:
            problems.append(f"loop={loop!r} but the cut opens on {a['clip']} and "
                            f"closes on {z['clip']}")
        elif loop == "repeat" and abs(a["start"] - z["start"]) > TOL:
            problems.append(f"loop='repeat' but the closing shot starts at {z['start']}, "
                            f"not the opening {a['start']}")
        elif loop == "wrap" and abs(z["start"] + z["dur"] - a["start"]) > 1.0 / FPS:
            problems.append(f"loop='wrap' but the closing shot ends at "
                            f"{z['start'] + z['dur']:.3f}, not the opening in-point "
                            f"{a['start']}")
    elif loop:
        problems.append(f"loop={loop!r} needs at least two shots")

    # --- claims --------------------------------------------------------------
    claims, t = [], 0.0
    for c in spec["claims"]:
        lines = c["lines"]
        c0 = float(c.get("from", t))
        c1 = float(c.get("to", total))
        if len(lines) > MAX_LINES:
            problems.append(f"claim {lines[0]!r} is {len(lines)} lines; the card holds "
                            f"{MAX_LINES}")
        for ln in lines:
            w = text_width(ln)
            if w is None:
                problems.append("cannot measure text: install Pillow or check the font")
                break
            if w * WIDTH_MARGIN > MAX_TEXT_W:
                problems.append(f"claim line {ln!r} measures {w:.0f}px at {CLAIM_SIZE}px, "
                                f"over the {MAX_TEXT_W}px card width — break it")
        if c0 < -TOL or c1 > total + TOL:
            problems.append(f"claim {lines[0]!r} runs {c0}-{c1}, outside the cut (0-{total:.3f})")
        claims.append([lines, round(c0, 3), round(c1, 3)])
        t = c1
    for (_, a1), (_, b0) in zip([(c[1], c[2]) for c in claims],
                                [(c[1], c[2]) for c in claims[1:]] or [(None, None)]):
        if b0 is not None and a1 > b0 + TOL:
            problems.append(f"claims overlap at {a1} > {b0}")
    if claims and abs(claims[-1][2] - total) > 0.01:
        problems.append(f"the last claim ends at {claims[-1][2]}s, leaving "
                        f"{total - claims[-1][2]:.2f}s of card with no type on it")

    clip_mod.save_grades(cache)

    # --- report --------------------------------------------------------------
    print(f"\n{slug}/{name}  —  {spec.get('eyebrow', '')}")
    print(f"  {'shot':34} {'clip':30} {'in':>6} {'dur':>6} {'pan':>5}  source")
    for label, clip, start, dur, srcnote, pan in notes:
        print(f"  {label:34} {clip[:30]:30} {start:6.2f} {dur:6.3f} {pan:+5.2f}  {srcnote}")
    drift = bars * BAR - total
    print(f"  {bars} bars = {total:.3f}s ({total_frames} frames"
          + (f", {drift * 1000:+.0f}ms off the bar grid" if abs(drift) > 1e-6 else ", exact")
          + f"), {len(shots)} shots, avg {span / max(len(shots), 1):.2f}s per shot, "
            f"loop={loop!r}")
    for lines, c0, c1 in claims:
        print(f"  claim {c0:5.2f}-{c1:5.2f}  " + " / ".join(lines))

    if problems:
        print(f"\n  {len(problems)} problem(s):")
        for p in problems:
            print(f"    - {p}")
        return False

    # --- music ---------------------------------------------------------------
    job = {"out": f"{name}_9x16.mp4", "body_dur": total, "body_frames": total_frames,
           "layout": "full" if full else "card",
           "eyebrow": spec.get("eyebrow"), "shots": shots, "claims": claims}
    # 608 keeps the whole 16:9 frame. Anything taller crops the sides, so it is
    # opt-in per cut and never the default.
    if spec.get("footage_h"):
        job["footage_h"] = int(spec["footage_h"])
    if "music" in spec:
        m = spec["music"]
        if isinstance(m, str):
            m = m if os.path.isabs(m) else os.path.normpath(os.path.join(social, m))
            if not os.path.exists(m):
                print(f"  music not found: {m}")
                return False
            # Seamless means the bed is the cut's own length, so it needs no fades
            # and the audio loops with the picture.
            bed_len = clip_mod.duration(m)
            job["music_seamless"] = abs(bed_len - total) <= 0.02
            print(f"  bed {os.path.basename(m)} {bed_len:.3f}s — "
                  + ("seamless, no fades" if job["music_seamless"] else
                     f"trimmed to {total:.3f}s, 0.25s edge fades (audible dip at the seam)"))
        job["music"] = m
    if spec.get("music_gain") is not None:
        job["music_gain"] = spec["music_gain"]

    # The .trf may have come from another page. Copy it in so one relative path and
    # one cwd cover the whole render.
    if trfs:
        dest_stab = os.path.join(social, "_stab")
        os.makedirs(dest_stab, exist_ok=True)
        for t in trfs:
            shutil.copy2(t, os.path.join(dest_stab, os.path.basename(t)))
        print(f"  copied {len(trfs)} .trf into social/_stab/")

    dest = os.path.join(social, f"{name}_jobs.json")
    json.dump({"jobs": [job]}, open(dest, "w", encoding="utf-8"), indent=1,
              ensure_ascii=False)
    print(f"  wrote {os.path.relpath(dest, ROOT)}")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ok = all(build(a) for a in sys.argv[1:])
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
