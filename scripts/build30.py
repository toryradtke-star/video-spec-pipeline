"""Turn a page's design.json into a render spec, and check it before it renders.

design.json is the only file you hand-author per page. It holds the beats: the
voiceover line, the captions and the shots for each. Everything else — clip
paths, grades, the caption timeline, the render spec — is derived.

The checks matter more than the conversion. Every one of them is a mistake made
at least once on this program:

  - a beat whose shots do not sum to its own length
  - beats that leave a gap or overlap on the timeline
  - a caption that runs outside the beat it belongs to
  - an in-point plus duration that runs off the end of the clip
  - a voiceover line too long to read in the time available

    python scripts/build30.py custom-labels [more-slugs ...]

Writes pages/<slug>/jobs.json. Grades any clip it has not measured before.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clips as clip_mod
import stab as stab_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "pages")

WPS = 2.1          # words/sec a read lands at without rushing
CARD = 3.0         # end card, appended by render30.py
TARGET = 30.0      # body + card, unless design.json overrides it with "target"
TOL = 0.001


def check(design, cache, folder="", slug_arg=""):
    """Validate and flatten. Returns (shots, captions, body, problems, notes)."""
    shots, captions, problems, notes = [], [], [], []
    t = 0.0

    for b in design["beats"]:
        name = b["name"]
        span = round(sum(s["dur"] for s in b["shots"]), 3)
        b0, b1 = t, round(t + span, 3)

        for s in b["shots"]:
            slate, start, dur = s["clip"], s["start"], s["dur"]
            # Two kinds of source. A slate code resolves into the proxy pools and gets
            # a measured grade. Anything with a path or an extension is an asset kept
            # beside the page — a screen capture of the product page, in practice —
            # which is already clean sRGB and must not be graded like camera footage.
            asset = bool(os.path.splitext(slate)[1]) or "/" in slate or "\\" in slate
            if asset:
                path = slate if os.path.isabs(slate) else os.path.join(folder, slate)
                if not os.path.exists(path):
                    problems.append(f"{name}: {slate} not found beside the page")
                    continue
                grade = None
            else:
                try:
                    path = clip_mod.resolve(slate)
                except SystemExit as e:
                    problems.append(f"{name}: {e}")
                    continue
                grade = clip_mod.grade_of(slate, cache)
            clip_len = clip_mod.duration(path)
            if start + dur > clip_len:
                problems.append(f"{name}: {slate} wants {start}+{dur}={start + dur:.1f}s "
                                f"but the clip is only {clip_len:.1f}s")
            shot = {"clip": slate, "src": path, "start": start, "dur": dur,
                    "grade": grade}
            if s.get("adjust"):
                shot["adjust"] = s["adjust"]
            if s.get("stabilize"):
                trf = os.path.join(folder, "_stab", stab_mod.trf_name(slate, start, dur))
                if os.path.exists(trf):
                    # Relative, forward slashes: vidstabtransform's `input=` will NOT
                    # accept a Windows drive colon, escaped or not (unlike drawtext's
                    # fontfile). render30.py runs ffmpeg from the page folder for this.
                    rel = os.path.join("_stab", stab_mod.trf_name(slate, start, dur))
                    # smoothing is in frames; higher is steadier but crops more.
                    sm = int(s.get("stab_smoothing", 30))
                    shot["stab"] = (f"vidstabtransform=input={rel.replace(os.sep, '/')}"
                                    f":smoothing={sm}:optzoom=1:interpol=bicubic")
                else:
                    problems.append(f"{name}: {slate} is marked stabilize but has no .trf "
                                    f"- run: python scripts/stab.py {slug_arg}")
            shots.append(shot)

        for text, c0, c1 in b.get("captions", []):
            if c0 < b0 - TOL or c1 > b1 + TOL:
                problems.append(f"{name}: caption {text!r} runs {c0}-{c1}, "
                                f"outside the beat at {b0}-{b1}")
            captions.append([text, c0, c1])

        # Once a line is actually recorded its own length is the truth, and the word
        # budget is only ever a stand-in for it. Checking the estimate against a beat
        # the real read already fits blocks a legitimate tighten; checking the file
        # catches the case the estimate cannot see, which is a slow read.
        words = len(b.get("vo", "").split())
        budget = span * WPS
        vo_path = b.get("voice")
        if vo_path and not os.path.isabs(vo_path):
            vo_path = os.path.join(folder, vo_path)
        if vo_path and os.path.exists(vo_path):
            read = clip_mod.duration(vo_path)
            flag = "OVER" if read > span + TOL else "ok"
            if flag == "OVER":
                problems.append(f"{name}: the recorded line is {read:.2f}s but the beat "
                                f"is only {span}s — it would be cut off")
            budget = read
        else:
            flag = "OVER" if words > budget + 0.5 else "ok"
            if flag == "OVER":
                problems.append(f"{name}: voiceover is {words} words in {span}s "
                                f"({budget:.1f} word budget) — it will rush")
        notes.append((name, b0, b1, span, len(b["shots"]), words, budget, flag))
        t = b1

    body = round(t, 3)
    # 30s is the house length, not a law. A page whose read is tight can run shorter
    # rather than pad the gaps between lines with dead air.
    target = float(design.get("target", TARGET))
    if abs(body + CARD - target) > 0.01:
        problems.append(f"body {body}s + {CARD}s card = {body + CARD}s, not {target}s")

    caps = sorted(captions, key=lambda c: c[1])
    for (t0, a1), (t1, _) in zip([(c[1], c[2]) for c in caps], [(c[1], c[2]) for c in caps[1:]] or [(None, None)]):
        if t1 is not None and a1 > t1 + TOL:
            problems.append(f"captions overlap at {a1} > {t1}")

    return shots, captions, body, problems, notes


def build(arg):
    """`slug` builds design.json; `slug:variant` builds design-<variant>.json.

    A variant is a full alternative cut of the same page kept side by side, so two
    versions can be compared without either overwriting the other.
    """
    slug, _, variant = arg.partition(":")
    folder = os.path.join(PAGES, slug)
    name = f"design-{variant}.json" if variant else "design.json"
    design = json.load(open(os.path.join(folder, name), encoding="utf-8"))
    cache = clip_mod.load_grades()

    shots, captions, body, problems, notes = check(design, cache, folder, arg)
    # The file is named for how long it actually runs. "30s" is this generation's
    # house length, not a promise every page has to keep.
    secs = int(round(float(design.get("target", TARGET))))
    clip_mod.save_grades(cache)

    print(f"\n{slug}  —  {design.get('title', slug)}")
    print(f"  {'beat':18} {'in':>6} {'out':>6} {'dur':>5} {'shots':>5} {'words':>6} {'read/bud':>9}")
    for name, b0, b1, span, n, words, budget, flag in notes:
        mark = "  <-- OVER" if flag == "OVER" else ""
        print(f"  {name:18} {b0:6.1f} {b1:6.1f} {span:5.1f} {n:5d} {words:6d} {budget:9.2f}{mark}")
    total_shots = len(shots)
    # No shot resolved — every one is already in `problems`, and an average over
    # nothing would raise before they get printed.
    avg = f"avg {body / total_shots:.2f}s per shot" if total_shots else "nothing resolved"
    print(f"  body {body}s + card {CARD}s = {body + CARD}s, {total_shots} shots, {avg}")

    if problems:
        print(f"\n  {len(problems)} problem(s):")
        for p in problems:
            print(f"    - {p}")
        return False

    spec = {"jobs": [{
        "out": f"{slug}_{secs}s_{variant}.mp4" if variant else f"{slug}_{secs}s.mp4",
        "body_dur": body,
        "title": design["title"],
        "closing": design.get("closing"),
        "shots": shots,
        "captions": captions,
    }]}
    # Passed through as-is so `false` survives and switches the bed off; a missing
    # key means the house bed. A relative path resolves against the page folder,
    # so a page can keep its own music beside it.
    if "music" in design:
        m = design["music"]
        if isinstance(m, str) and not os.path.isabs(m):
            m = os.path.join(folder, m)
            if not os.path.exists(m):
                print(f"  music not found: {m}")
                return False
        spec["jobs"][0]["music"] = m
    if design.get("music_gain") is not None:
        spec["jobs"][0]["music_gain"] = design["music_gain"]
    if design.get("voice"):
        spec["jobs"][0]["voice"] = design["voice"]

    # One recording per beat, each placed at the beat's own in-point. A missing file
    # is skipped rather than fatal, so a part-recorded read still renders.
    lines, missing = [], []
    for (name, b0, *_ ), b in zip(notes, design["beats"]):
        f = b.get("voice")
        if not f:
            continue
        path = f if os.path.isabs(f) else os.path.join(folder, f)
        (lines if os.path.exists(path) else missing).append(
            {"file": path, "at": b0} if os.path.exists(path) else name)
    # The closing line sits on the end card, which is not a beat, so it is named separately.
    card_vo = design.get("voice_card")
    if card_vo:
        path = card_vo if os.path.isabs(card_vo) else os.path.join(folder, card_vo)
        if os.path.exists(path):
            lines.append({"file": path, "at": body})
        else:
            missing.append("Close")

    if lines:
        spec["jobs"][0]["voice_lines"] = lines
        total = len(design["beats"]) + (1 if card_vo else 0)
        print(f"  voiceover: {len(lines)} of {total} lines placed")
    if missing:
        print(f"  voiceover missing for: {', '.join(missing)}")

    dest = os.path.join(folder, f"jobs-{variant}.json" if variant else "jobs.json")
    json.dump(spec, open(dest, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"  wrote {os.path.relpath(dest, ROOT)}")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ok = all(build(s) for s in sys.argv[1:])
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
