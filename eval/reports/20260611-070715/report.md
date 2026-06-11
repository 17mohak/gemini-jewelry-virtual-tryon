# Evaluation run 20260611-070715

Heuristic metrics flag outputs for human review; they do not certify
quality. Fill the human rubric column while inspecting each image:
`fidelity /5, identity /5, integration /5, lighting /5, placement /5`.

Human review completed 2026-06-11 (all 15 outputs inspected against their
input photo and product photo).

| case | type | status | aspect | border | noise | sharp | bright | skin | flags | human rubric |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| necklace-gemset | necklace | ok | 0.0 | 2.07 | 1.32 | 1.249 | -2.97 | n/a | noise_match=1.32 outside (0.75, 1.3) | 4/5/4/5/5 — flag is mild grain amplification on the wall (just over the 1.30 limit); medallion band mildly simplified; reviewed acceptable |
| necklace-gold-beads | necklace | ok | 0.0 | 2.02 | 1.055 | 1.079 | -2.4 | n/a | - | 5/5/5/5/4 — prompt_hint correctly excluded the product photo's earrings; darker clasp bead rendered visible mid-strand |
| necklace-cross-pendant | necklace | ok | 0.0 | 2.17 | 1.094 | 1.103 | -1.88 | n/a | - | 5/5/5/5/4 — pendant slightly large vs the scale anchor |
| necklace-coral-coin | necklace | ok | 0.0 | 2.04 | 1.126 | 1.147 | -3.47 | n/a | - | 4/5/5/5/4 — drapes looser than the product's tight collar style |
| earrings-gold-drop | earrings | ok | 0.0 | 1.93 | 1.097 | 1.106 | -0.88 | n/a | - | 4/5/4/5/4 — both earrings emerge below the hair, no invented ears; slightly long vs anchor; upper rings overlap a hair strand they should sit behind |
| earrings-gold-hoop | earrings | ok | 0.0 | 1.84 | 1.067 | 1.072 | -1.16 | n/a | - | 4/5/4/4/5 — hoop tube rendered thinner than the product photo; catalog description ("thick") contradicted the photo — superseded by re-run 20260611-071658 after the metadata fix |
| ring-three-stone-diamond | ring | ok | 0.0 | 1.89 | 1.043 | 1.085 | -1.99 | n/a | - | 5/5/5/5/5 — single ring per hint, correct finger, correct scale |
| ring-gold-filigree | ring | ok | 0.0 | 2.01 | 1.087 | 1.111 | -2.23 | n/a | - | 4/5/5/5/4 — statement face renders slightly wider than the finger |
| bracelet-enamel-bangle | bracelet | ok | 0.0 | 2.32 | 1.27 | 1.214 | -4.26 | n/a | - | 4/5/5/5/4 — enamel pattern mildly simplified; sits slightly high at the wrist crease |
| bracelet-gold-spiral | bracelet | ok | 0.0 | 1.99 | 1.164 | 1.158 | -3.02 | n/a | - | 5/5/4/5/5 — four coils and cone finials preserved; coil spacing slightly airy |
| clothing-white-oxford | top | ok | 0.0 | 2.03 | 1.011 | 1.089 | 2.43 | 1.025 | - | 5/4/5/5/5 — collar/buttons/pocket faithful, hem below hips, lower body untouched; mild face smoothing |
| clothing-breton-top | top | ok | 0.0 | 1.92 | 1.585 | 1.775 | -3.09 | 1.043 | noise_match=1.585 outside (0.75, 1.3); sharpness_match=1.775 outside (0.7, 1.4) | 5/4/5/4/5 — flags are the documented stripe-energy metric artifact; stripes even and contour-following; reviewed clean |
| clothing-green-wrap-dress | dress | ok | 0.0 | 2.29 | 1.024 | 1.143 | -8.81 | 1.034 | - | 5/4/5/4/5 — hem at lower calf per product, ankles and sneakers preserved; mild face smoothing |
| clothing-black-dress | dress | ok | 0.0 | 2.41 | 1.048 | 1.077 | -9.4 | 1.035 | - | 4/4/4/4/5 — hem at knee, footwear preserved; input's opaque leggings replaced with sheer tights (new FM-E, invented under-layer) |
| clothing-blue-jeans | trousers | ok | 0.0 | 2.41 | 1.025 | 1.157 | 1.37 | 0.997 | - | 5/4/4/4/5 — five-pocket design and wash faithful, top untouched; small white socks invented at the ankles (FM-E) |

Threshold reference: aspect_drift<=0.10, border<=30, noise 0.75-1.30, sharpness 0.70-1.40, |brightness|<=15, lower_skin_ratio>=0.50.
