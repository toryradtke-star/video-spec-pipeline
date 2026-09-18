# video-spec-pipeline

Build product-page videos and vertical social cuts from a single hand-authored JSON file per
page, with a validation layer that refuses to emit a spec that would not render correctly.

Two outputs share one source of truth:

1. **A 30-second 16:9 product-page video.** One shape for every page in a catalog — the shape is
   `TEMPLATE-30s.md`, read that first.
2. **6–12s 9:16 social cuts**, no voiceover, built by re-cutting shots the page videos have
   already vetted.

The tooling is ffmpeg underneath. What sits on top is the part worth having: a spec format that
inherits, and a build step that checks the spec against the footage before a single frame is
rendered.

## Why validation is the whole point

Rendering a 30-second cut is slow, and almost every failure is silent — the video renders fine
and is simply *wrong*. A caption that outlives its beat, an in-point 2 seconds from the end of a
4-second clip, a voiceover line nobody can read in the time allowed. You find those by watching
the output, which means you find them late.

So `build30.py` refuses to write a spec that would not work. It checks that a beat's shots sum to
the beat's own length, that beats leave no gap on the timeline, that captions stay inside their
beat, that an in-point plus duration does not run off the end of the clip, and that each
voiceover line is readable in the time available.

**Every one of those checks is a mistake this program made at least once.** That is the selection
criterion — not what seemed worth checking, but what actually went wrong.

`build_social.py` does the same for vertical cuts, and its checks are different because the
failure modes are:

- a duration off the bar grid, which puts the music bed's loop out of phase
- an in-point plus duration that runs off the end of the clip
- a claim line too wide for the frame, or a claim of more than three lines
- a stale `.trf` — stabilisation data is keyed to the window, so a changed duration invalidates it
- a cut that does not loop, when it says it should

## Setup

Requires `ffmpeg`/`ffprobe` on PATH, Python 3.9+, and Pillow for text measurement.

Everything machine- or brand-specific lives in `scripts/config.py` and reads from the
environment:

```
VSP_PROXIES    footage proxies, one subfolder per pool     (default: ./footage/proxies)
VSP_ORIGINALS  full-resolution originals, same naming      (default: ./footage/originals)
VSP_OVERLAYS   logo.png and bed.mp3                        (default: ./overlays)
VSP_FONT       a .ttf for captions                         (default: DejaVuSans-Bold)
VSP_BRAND      end-card and caption-rule colour, 0xRRGGBB  (default: 0x1f6feb)
VSP_CLOSING    end-card closing line
```

Footage resolves **by convention, not by manifest**. A slate code like `1K 02 A` is
`<pool><roll> <take> <cam>`; the leading character selects a folder via `config.POOLS` and the
rest matches a filename stem. There is no catalog file to keep in sync, because a catalog file
is one more thing that can be wrong. `survey.py` builds a visual index instead.

## Make a video

```
python scripts/survey.py                        # once: visual index of every clip
python scripts/clips.py strip "2G 01 B"         # pick in/out points off a contact strip
                                                # then hand-author pages/<slug>/design.json
python scripts/build30.py <slug>                # validate + write jobs.json
python scripts/render30.py pages/<slug>/jobs.json
python scripts/qc30.py <slug>                   # contact sheet of the finished cut
```

## Social cuts

A social cut is **full screen** by default: the footage fills the 1080×1920 frame and the claim
sits on it over a gradient scrim, with the logo bottom-centre. `"layout": "card"` is the
alternative — footage in a window on a brand-coloured card — kept for a frame whose sides cannot
be cropped at all.

```
python scripts/build_social.py <slug>/<name>            # validate + write <name>_jobs.json
python scripts/pan_social.py <slug>/<name>              # pick each shot's pan off a sheet
python scripts/stab_social.py <slug>/<name>             # only if a shot is stabilised
python scripts/render_social.py pages/<slug>/social/<name>_jobs.json
python scripts/level_social.py <slug>/<name> --apply    # match the shots' brightness
python scripts/build_social.py <slug>/<name> && python scripts/render_social.py ...   # again
python scripts/qc_social.py <slug>/<name>               # sheet, loop seam, cut steps
```

Levelling is **iterative and comes after the pans are settled** — a pan changes which part of the
frame is in shot and therefore its brightness, so levelling first wastes the pass.

`pages/<slug>/social/<name>.json` is the only hand-authored file, and it is short because it
**inherits**: `"from": "example-product:Payoff:0"` pulls that page's clip, in-point, brightness
`adjust` and stabilisation verbatim. Those windows have already been measured for shake, matched
for brightness and screened. Re-picking them by hand would throw that away.

### Things worth knowing before authoring one

- **They loop, and that is the point.** Sub-15s verticals complete far more often than 30s+ ones,
  and a rewatch counts twice in short-form distribution. Put the logo in the chrome rather than
  on an end card, so there is nothing to break the loop.
- **Two loop forms.** `"repeat"` closes on the opening window again, and needs only a short
  closing shot. `"wrap"` closes on the footage *immediately before* the opening in-point, so the
  loop is continuous in the source — but it needs headroom that a clip starting at @0.0 does not
  have. On one tight macro push, `repeat` measured 10.8 dB at the seam and `wrap` 28.4 dB on the
  same shots.
- **Seam thresholds do not transfer between edit styles.** A 29 dB baseline measured on 0.6s
  crossfades is meaningless for hard cuts: the crossfade's failure mode is a ghost frame, the
  hard cut's is reading as a jump to a different subject. ~18 dB looks right on a slow push.
- **Length is on the music bed's bar grid.** At 108 BPM a bar is 2.2222s, so 3/4/5 bars =
  6.667 / 8.900 / 11.100s. Only a multiple of 3 bars lands on a whole frame, so the total is
  frame-snapped and the closing shot absorbs the residual. A cut whose length is exactly the
  bed's loop length gets a seamless bed with no fades; anything else gets 0.25s edge fades and a
  small audible dip.
- **Full screen reads from the originals, not the proxies.** A 9:16 crop keeps ~32% of the width:
  608×1080 off a 2048×1080 proxy needs a 1.78× upscale, while 1215×2160 off a 4096×2160 original
  is a downscale. `clips.original()` maps the slate and `build_social.py` switches automatically.
- **Every full-screen shot needs its pan chosen, and `pan_social.py` is how.** The subject is
  centred in maybe a third of shots. Left at centre, the first full-screen pass put a wide sign
  through the right edge and a door graphic almost entirely out of frame. There is no way to
  compute the right pan — the subject is wherever the camera put it — so the job is to make
  choosing fast and a bad choice obvious.
- **Counterintuitively, WIDE shots survive a vertical crop and tight ones do not.** In a tight
  macro the subject already fills the width, so there is nothing to spare. Pages whose 16:9 cut
  leads on a macro often have to invert for the vertical and lead on the wide.
- **Some shots cannot go full screen at all.** A graphic painted across more than a third of the
  frame has no pan that holds it, because the width *is* the subject. Replace the shot rather
  than cropping it. Judge by whether the graphic survives: a floor arrow with a partly-visible
  word still reads; a bisected slogan does not.
- **Cropping magnifies shake by the crop factor.** One shot measured 0.10 across the full frame
  and 1.13 in the 9:16 crop. Re-check shake *after* settling the pans, not before.
- **Full screen makes legible what was not.** Artwork the source page called "not identifiable"
  at 1920×1080 can be perfectly readable once cropped. Re-read every brand-mark and artwork note
  in the source page before shipping a vertical cut.
- **A stabilised shot needs its own `.trf` on the full-resolution path.** A `.trf` holds
  transforms in pixels, so a proxy-measured file describes shifts half the size a 4K frame needs,
  and `vidstabtransform` quietly applies half a correction. `stab_social.py` re-measures on the
  real source.
- **Re-level every cut, always.** Inherited `adjust` values were tuned against *different*
  neighbours; re-ordering the shots invalidates all of them. The first batch rendered with cut
  steps of 33–52 YAVG. `level_social.py` measures the delivery file and works backwards, and it
  is **iterative** — `eq=brightness` is not a clean offset on a very dark frame, so run it two or
  three times and watch the step converge.
- **The mean sets the target; the histogram sets the limit.** A shot can read 133 YAVG because a
  white sheet fills half the frame, not because the scene is bright. Levelling it to 105 by
  offset took 17% of one frame to near-black and lost the background entirely — a worse picture,
  by a metric that was satisfied. `level_social.py` backs a correction off before it clips. If it
  holds several shots back and a step survives, the shots genuinely do not match: use `--target=`
  nearer the cut's own majority, or pick a different shot.
- **`shake.py` across a whole social cut is meaningless** — every hard cut registers as a huge
  acceleration. Scan inside each shot.
- **`qc_social.py` reports the step at each cut, not a global min/max.** A global range cannot
  tell a flash apart from a shot that darkens on its own, which is how one cut was briefly
  reported as flashing while its four shots sat inside 12 points of each other.

## Layout

```
TEMPLATE-30s.md      what a video is: the six beats and the rules
_assets/             gradient scrims for the full-screen social layout
scripts/
  config.py          paths, pools, brand — everything machine-specific
  survey.py          visual index of every clip, by slate code
  clips.py           slate code -> proxy path; duration; grade cache; contact strips
  grade.py           measures a per-clip colour correction
  build30.py         design.json -> jobs.json, with validation
  render30.py        jobs.json -> the 30s mp4
  qc30.py            contact sheet of a finished cut
  build_social.py    social spec -> jobs, with validation
  render_social.py   9:16 cut, full-screen or card layout
  level_social.py    match shot brightness in a finished cut, with a clipping guard
  qc_social.py       sheet + loop seam + per-cut brightness step
  pan_social.py      every shot at five pans, to pick the crop by eye
  stab.py            stabilisation measured on the proxy
  stab_social.py     stabilisation measured on the source a full-screen cut reads
  genimg.py          reference stills for AI-generated shots
pages/
  example-product/   the schema, annotated
  <slug>/
    design.json      the only hand-authored file: beats, VO, captions, shots
    script.md        editorial: VO, captions, claims and their sources
    shotlist.md      editorial: why each shot, continuity, open items
    jobs.json        generated
    social/
      <name>.json          hand-authored social cut, inherits from built pages
      <name>_jobs.json     generated
```

`design.json` is the source of truth for a page. `script.md` and `shotlist.md` are editorial —
the reasoning, the continuity notes and the release questions, which no script can generate.

## Mixed real and generated footage

The pipeline handles both, and the difference matters mechanically. Generated clips are
typically delivered at 1280×720 with no higher-resolution original, so their 9:16 crop is 405×720
and needs a 2.67× upscale — which holds up better than it should, because generated footage has
no grain to magnify. `build_social.py` detects which kind a shot is from its reference form: a
slate code resolves through the footage library, while a path or a filename is an asset kept
beside its page.

`genimg.py` generates reference stills so a frame can be approved cheaply before it is fed to a
video model as a first frame. It bans lettering in prompts by default, because generated text
garbles — pages that genuinely need a word in frame override the suffix and accept the retry
cost.

## ffmpeg gotchas that cost time

- **`drawtext` and a Windows drive colon.** The path goes inside a filter string, so the colon
  has to be escaped there — and must *not* be escaped anywhere else. `config.font_drawtext()` is
  the escaped form, `config.FONT` the plain one. Getting it wrong fails at render, not at import.
- **Some builds reject an escaped drive colon in `fontfile` outright.** A driveless path
  (`/Windows/Fonts/…`) works where the escaped form does not.
- **`colorlevels` on 10-bit input** crushes to black unless prefixed with `format=rgb24`.
- **Correct levels per channel**, or a saturation boost goes yellow.
- **`drawbox` understands `ih`/`iw` but not `H`/`W`; `drawtext` understands both.**
- **A caption band at `black@0.42` is a tint, not a mask.** It does not hide what is behind it —
  a brand mark in the lower third reads straight through. Render the band onto a still to check a
  framing before committing:
  `drawbox=x=0:y=805:w=1920:h=150:color=black@0.42:t=fill`
- **Not every font has every glyph.** A missing double prime (`″`, U+2033) drops a tofu box on
  screen for the length of the caption. Use straight quotes.
- **`fit()` scales to cover and centre-crops.** A 1900×940 screen capture loses ~130px per side;
  a 16:9 clip loses nothing. There is no per-shot crop in the 16:9 pass.
- **Mixed frame rates do not multicam-sync without a conform.** 23.976 and 59.94 takes of the
  same setup will drift.
- **`shake.py` measures camera movement, not focus.** A locked-off shot behind the focus plane
  passes every check and is still soft. Read the QC sheet.
- **Shots are trimmed to a common brightness, not left as graded.** `grade.py` measures each clip
  alone and cannot know what a shot cuts against. Measure YAVG *after* the grade and after the
  scale-and-crop, then set `adjust` to bring every shot toward ~105. Raw spreads of 50+ points
  flash at the cuts.
- **Size beats after the voiceover exists, not before.** The words-per-second budget is a
  stand-in for a read that has not been recorded. Once the wav is there, `build30.py` checks the
  file's real length instead.
- **Map a delivered take to lines by transcribing it**, not by counting silences — lines have
  internal pauses.

## Licence

MIT. See `LICENSE`.
