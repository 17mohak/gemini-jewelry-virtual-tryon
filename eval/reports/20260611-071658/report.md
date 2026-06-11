# Evaluation run 20260611-071658

Heuristic metrics flag outputs for human review; they do not certify
quality. Fill the human rubric column while inspecting each image:
`fidelity /5, identity /5, integration /5, lighting /5, placement /5`.

| case | type | status | aspect | border | noise | sharp | bright | skin | flags | human rubric |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| earrings-gold-hoop | earrings | ok | 0.0 | 1.96 | 1.051 | 1.064 | -1.46 | n/a | - | 5/5/5/5/4 — slender tube now matches the product photo after the catalog metadata fix; only the visible ear receives a hoop (fully hidden ear left bare, by design) |

Threshold reference: aspect_drift<=0.10, border<=30, noise 0.75-1.30, sharpness 0.70-1.40, |brightness|<=15, lower_skin_ratio>=0.50.