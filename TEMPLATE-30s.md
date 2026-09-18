# The 30s template

What every product-page video is. One shape, so a catalog of them stays consistent and none of
them needs inventing from scratch.

The point of a fixed template is that **the edit is decided before anyone opens a clip bin.**
Shot selection varies per page; structure does not.

## The six beats

30.0s total: 27.0s of footage plus a 3.0s end card.

| Beat | Length | What it does | Scope |
|---|---|---|---|
| 1 Hook | ~4s | Name the product, show it in real use | per page |
| 2 Where it goes | ~5s | The surfaces or contexts it lives in | per page |
| 3 Made in-house | ~5s | Production. Answers "who makes this" and "how many" | **reusable** |
| 4 Ordering | ~8.5s | A customer buying it. Carries the spec claims in caption | **reusable** |
| 5 Payoff | ~4.5s | Delivery, unboxing, the result. Hold it, don't cut it | **reusable** |
| 6 Close | 3.0s | Brand end card | **reusable** |

**Beats 3–6 are ~20 of the 30 seconds and are product-agnostic.** The press, the laptop and the
box do not care which variant the page sells. Only beats 1 and 2 — about 9 seconds — need
page-specific footage. That is what makes a large catalog tractable, and it is the answer for
pages with no matching footage of their own.

**Beat 5 is swappable when the page demands it.** A category hub has no cart and no proof, so
its own answer to "which one do I need" becomes the payoff instead. Check whether the page is a
product page or a hub before assuming the six beats fit as written.

**Do not clone the sibling video.** Read the nearest finished page's `script.md` first and build
on the claims that page has and the sibling does not. Two videos for pages one click apart
should share no claim set and no frame.

## Rules

**Cut rate.** ~10 shots across the 27s, averaging 2.5–3.0s. Split beats into 2–3 shots each.
Land cuts on caption boundaries where you can, so the picture changes with the claim rather than
fighting it. **Beat 5 is the exception** — the payoff is one continuous action. Hold it.

**Voiceover: 2.1 words/sec, 63 words maximum** — but only until the read exists. That figure
sizes a script before anyone has recorded it. **Once the wav is there, the beats are sized to
the audio**: each beat is its line plus a 0.55–0.90s breath, with 1.3–1.4s on the last body beat
because it is the payoff. `build30.py` checks the recorded file's length when it can and falls
back to the word budget when it cannot.

**30.0s is the house length, not a law.** A page whose read is tight runs shorter rather than
padding the gaps — set `"target"` in `design.json`. Laying out to 30s from the word estimate
once shipped a cut with 9.6s of dead air in it.

**The caption states the claim; the VO gives the texture. Never both.** Precise numbers go in
the caption — "fifty-two by a hundred and twenty inches" is unsayable. And never narrate the
picture: if the shot shows a box opening, the VO does not say "and it arrives."

**Captions.** Uppercase, white, fontsize 52. Black band `@0.42`, full width, 150 tall, top edge
at `H − 275`. Text baseline `H − 215`. Brand rule 260 × 7 at text y + 76.

**Every claim has to survive with the sound off.** Product-page video autoplays muted behind a
poster more often than not. If the claim only exists in the voiceover, it does not exist.

**16:9 only, 1920×1080.** Native framing, no crop, no pan. A 9:16 social cut is a separate pass,
not a crop of this one — a 9:16 crop keeps only the middle ~30% of the width and slices anything
wide. See "Social cuts" in `README.md`. It changes nothing here.

**End card.** Full-bleed brand colour, logo, product title, white rule, closing line.

## Claims

Two rules, both learned the hard way:

- **Verify every claim against the live product page, and date the check.** Specs change. A
  claim that was true when the script was written is not necessarily true at render.
- **Never borrow a competitor's claim.** If a reference video says "dishwasher safe" and your
  own page says "water-resistant", those are different claims and only one of them is yours.
  Check the page before claiming a material, a durability figure or a turnaround.

Write the claims and their sources into the page's `script.md`. That file is editorial — the
reasoning, the continuity notes and the open questions, which no script can generate.

## Reference

`pages/example-product/` is the schema, annotated. Start there.
