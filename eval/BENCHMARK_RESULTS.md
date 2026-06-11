# Benchmark results

## Full catalog sweep — run `20260611-070715` (+ re-run `20260611-071658`)

Model `gemini-3.1-flash-image` · all **15** catalog cases (10 jewelry + 5
clothing) · image-only, zero video credits spent. Raw outputs live in the
gitignored `eval/runs/`; the reviewed reports (machine metrics + filled human
rubric) are committed under [`eval/reports/`](reports/).

### Headline

**15/15 cases generated successfully, 0 API failures.** All 15 were human-
reviewed against their input photo and product photo. No hard failures: no
identity loss, no anatomy errors, no hem drift, no leg erasure, no invented
ears, no background drift.

- `aspect_drift` = **0.0 on all 15 cases** (imageConfig pinning holds
  catalog-wide).
- `border_preservation` ≤ 2.41 everywhere (background essentially untouched).
- `lower_skin_ratio` ≥ 0.997 on all 5 clothing cases (no visible-skin loss —
  the leg-erasure failure mode stayed fixed across every garment type).
- 2 metric flags, both resolved on review as **metric artifacts / marginal**
  (see below), not visual defects.

### Scores (machine metrics + human rubric, fid/id/integ/light/place out of 5)

| case | aspect | border | noise | sharp | bright | skin | flags | human rubric |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| necklace-gemset | 0.0 | 2.07 | 1.32 | 1.25 | -3.0 | — | noise | 4/5/4/5/5 — flag is mild grain *amplification* on the wall, just over the 1.30 limit; medallion band mildly simplified; reviewed acceptable |
| necklace-gold-beads | 0.0 | 2.02 | 1.06 | 1.08 | -2.4 | — | – | 5/5/5/5/4 — prompt_hint correctly excluded the product photo's earrings; darker clasp bead visible mid-strand |
| necklace-cross-pendant | 0.0 | 2.17 | 1.09 | 1.10 | -1.9 | — | – | 5/5/5/5/4 — pendant slightly large vs the scale anchor |
| necklace-coral-coin | 0.0 | 2.04 | 1.13 | 1.15 | -3.5 | — | – | 4/5/5/5/4 — drapes looser than the product's tight collar style |
| earrings-gold-drop | 0.0 | 1.93 | 1.10 | 1.11 | -0.9 | — | – | 4/5/4/5/4 — both earrings emerge below the hair, no invented ears; slightly long vs anchor; upper rings overlap one hair strand |
| earrings-gold-hoop (re-run) | 0.0 | 1.96 | 1.05 | 1.06 | -1.5 | — | – | 5/5/5/5/4 — slender tube matches the product photo after the metadata fix; fully hidden ear left bare, by design |
| ring-three-stone-diamond | 0.0 | 1.89 | 1.04 | 1.09 | -2.0 | — | – | 5/5/5/5/5 — single ring per hint, correct finger, correct scale |
| ring-gold-filigree | 0.0 | 2.01 | 1.09 | 1.11 | -2.2 | — | – | 4/5/5/5/4 — statement face renders slightly wider than the finger |
| bracelet-enamel-bangle | 0.0 | 2.32 | 1.27 | 1.21 | -4.3 | — | – | 4/5/5/5/4 — enamel pattern mildly simplified; sits slightly high at the wrist crease |
| bracelet-gold-spiral | 0.0 | 1.99 | 1.16 | 1.16 | -3.0 | — | – | 5/5/4/5/5 — four coils and cone finials preserved; coil spacing slightly airy |
| clothing-white-oxford | 0.0 | 2.03 | 1.01 | 1.09 | 2.4 | 1.03 | – | 5/4/5/5/5 — collar/buttons/pocket faithful, hem below hips, lower body untouched; mild face smoothing |
| clothing-breton-top | 0.0 | 1.92 | 1.59 | 1.78 | -3.1 | 1.04 | noise/sharp | 5/4/5/4/5 — known stripe-energy **metric artifact**; stripes even and contour-following; reviewed clean |
| clothing-green-wrap-dress | 0.0 | 2.29 | 1.02 | 1.14 | -8.8 | 1.03 | – | 5/4/5/4/5 — hem at lower calf per product, ankles and sneakers preserved; mild face smoothing |
| clothing-black-dress | 0.0 | 2.41 | 1.05 | 1.08 | -9.4 | 1.04 | – | 4/4/4/4/5 — hem at knee, footwear preserved; input's opaque leggings replaced with sheer tights (**FM-E**, invented under-layer) |
| clothing-blue-jeans | 0.0 | 2.41 | 1.03 | 1.16 | 1.4 | 1.00 | – | 5/4/4/4/5 — five-pocket design and wash faithful, top untouched; small white socks invented at the ankles (FM-E) |

*(earrings-gold-hoop row shows the re-run; the first attempt rendered the
hoop tube thinner than the product photo and is recorded in the sweep report.)*

### Fix applied during the sweep

The first `earrings-gold-hoop` output rendered a noticeably thinner hoop than
the product photo. Root cause: **catalog metadata**, not the prompt or model —
the description said "thick polished gold hoop" while the product photo shows
a slender hoop, so the text anchor and the image anchor disagreed. Fix: the
description was corrected to match the photo ("slender... subtle lengthwise
ridge") and the prompt_hint now pins the tube thickness to the product photo.
Only this one case was re-generated (run `20260611-071658`): clean metrics,
faithful slender tube.

### Caveats recorded

- **Stripe/pattern metric artifact** (known): pattern-heavy garments inflate
  the global noise/sharpness parity metrics — the breton top flags every run
  while reviewing clean. Treat these two metrics as advisory for
  striped/patterned items; a background-only mask remains the future fix.
- **Marginal grain amplification** on the ornate gem-set necklace (noise 1.32
  vs limit 1.30) — visually a slight texture increase on the wall, not a
  defect; kept in the failure gallery as a borderline example.
- **New failure mode FM-E (invented under-layers)**: when a dress/trousers
  swap removes a garment the product doesn't replace (opaque leggings under a
  knee-length dress; bare ankles in sneakers), the model sometimes invents a
  plausible under-layer (sheer tights, white socks). Cosmetically reasonable
  but technically out of contract; documented in
  [FAILURES.md](FAILURES.md), not prompt-patched speculatively.
- **Mild face smoothing ("AI gloss")** persists at low level on all 5
  full-body clothing edits (identity 4/5) — known FM-D, reduced by the
  photographic-character section but not eliminated.
- Results are on the synthetic benchmark inputs committed to the repo; real
  photos vary more.

### Decision

The full catalog is verified at the image level. Both audit failure modes
(hem drift / leg erasure, earring omission) remain fixed catalog-wide, and no
new hard failure appeared. Submission-ready on image quality; remaining
imperfections are documented above and in [FAILURES.md](FAILURES.md).

---

## Hard subset — run `20260611-054604` (historical)

Model `gemini-3.1-flash-image` · 6 hard cases · image-only. This was the
first run after prompt v2 + aspect pinning; it validated the two audit fixes
before the full sweep above.

| Audit failure | v1 evidence | v2 result |
| --- | --- | --- |
| Hem drift + leg erasure (FM-A) | [result_wrap_dress.jpg](../docs/demo/result_wrap_dress.jpg) — dress rendered past product length; on a real photo, floor-length with legs erased | [result_wrap_dress_v2.jpg](../docs/demo/result_wrap_dress_v2.jpg) — hem at the lower calf per product photo; ankles and sneakers visible; `lower_skin_ratio 1.03` |
| Earring omission under hair (FM-B) | [result_earrings.jpg](../docs/demo/result_earrings.jpg) — one earring silently omitted | [result_earrings_v2.jpg](../docs/demo/result_earrings_v2.jpg) — both earrings render, each emerging below the hair, no invented ears |
| Framing drift (FM-7) | ring case re-cropped wider in v1 | `aspect_drift = 0.0` on **all six** cases (imageConfig pinning) |

| case | aspect | border | noise | sharp | bright | skin | flags | human rubric (fid/id/integ/light/place, /5) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| necklace-cross-pendant | 0.0 | 1.9 | 1.04 | 1.04 | -0.7 | — | – | 4/5/5/5/4 — pendant renders slightly large vs the 2-3 cm anchor |
| earrings-gold-drop | 0.0 | 1.8 | 1.11 | 1.11 | -0.6 | — | – | 5/5/4/5/5 — one hoop overlaps a hair strand it should sit behind |
| ring-three-stone-diamond | 0.0 | 1.9 | 1.05 | 1.09 | -2.0 | — | – | 5/5/5/5/5 — correct finger, scale, single ring per hint |
| bracelet-enamel-bangle | 0.0 | 2.2 | 1.29 | 1.22 | -3.9 | — | – | 4/5/5/5/5 — inner-band floral pattern mildly simplified |
| clothing-breton-top | 0.0 | 2.1 | 1.55 | 1.74 | -1.0 | 1.01 | noise/sharp | 5/4/5/4/5 — flags are a **metric artifact** (stripes add real edge energy vs the plain tee they replaced); reviewed clean |
| clothing-green-wrap-dress | 0.0 | 2.2 | 1.02 | 1.13 | -8.5 | 1.03 | – | 4/4/4/4/5 — hem correct, legs preserved; mild face smoothing remains |
