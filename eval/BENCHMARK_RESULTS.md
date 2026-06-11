# Benchmark results — hard subset, prompt v2 + aspect pinning

Run `20260611-054604` · model `gemini-3.1-flash-image` · 6 cases · image-only
(raw outputs and machine report live in `eval/runs/`, which is gitignored;
this file records the reviewed results).

## Headline

All six hard cases passed human review. The two failure modes that motivated
this pass are **fixed on the benchmark inputs**:

| Audit failure | v1 evidence | v2 result |
| --- | --- | --- |
| Hem drift + leg erasure (FM-A) | [result_wrap_dress.jpg](../docs/demo/result_wrap_dress.jpg) — dress rendered past product length; on a real photo, floor-length with legs erased | [result_wrap_dress_v2.jpg](../docs/demo/result_wrap_dress_v2.jpg) — hem at the lower calf per product photo; ankles and sneakers visible; `lower_skin_ratio 1.03` |
| Earring omission under hair (FM-B) | [result_earrings.jpg](../docs/demo/result_earrings.jpg) — one earring silently omitted | [result_earrings_v2.jpg](../docs/demo/result_earrings_v2.jpg) — both earrings render, each emerging below the hair, no invented ears |
| Framing drift (FM-7) | ring case re-cropped wider in v1 | `aspect_drift = 0.0` on **all six** cases (imageConfig pinning) |

## Scores

| case | aspect | border | noise | sharp | bright | skin | flags | human rubric (fid/id/integ/light/place, /5) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| necklace-cross-pendant | 0.0 | 1.9 | 1.04 | 1.04 | -0.7 | — | – | 4/5/5/5/4 — pendant renders slightly large vs the 2-3 cm anchor |
| earrings-gold-drop | 0.0 | 1.8 | 1.11 | 1.11 | -0.6 | — | – | 5/5/4/5/5 — one hoop overlaps a hair strand it should sit behind |
| ring-three-stone-diamond | 0.0 | 1.9 | 1.05 | 1.09 | -2.0 | — | – | 5/5/5/5/5 — correct finger, scale, single ring per hint |
| bracelet-enamel-bangle | 0.0 | 2.2 | 1.29 | 1.22 | -3.9 | — | – | 4/5/5/5/5 — inner-band floral pattern mildly simplified |
| clothing-breton-top | 0.0 | 2.1 | 1.55 | 1.74 | -1.0 | 1.01 | noise/sharp | 5/4/5/4/5 — flags are a **metric artifact** (stripes add real edge energy vs the plain tee they replaced); reviewed clean |
| clothing-green-wrap-dress | 0.0 | 2.2 | 1.02 | 1.13 | -8.5 | 1.03 | – | 4/4/4/4/5 — hem correct, legs preserved; mild face smoothing remains |

## Caveats recorded

- **Pattern-heavy garments inflate the global noise/sharpness parity metrics**
  (the breton flag). Future improvement: compute parity on a background-only
  mask. Until then, treat these two metrics as advisory for striped/patterned
  items.
- Mild "AI gloss" (face smoothing) persists at low levels on full-body
  clothing edits — reduced by the photographic-character prompt section but
  not eliminated. Tracked as FM-D.
- These results are on the synthetic benchmark inputs. The real-photo hard
  cases (night flash, busy background) reproduced the same fixes informally
  during development, but the committed benchmark only ships synthetic people.

## Decision

Improvement is meaningful and consistent → the full 15-case catalog sweep
(`python eval/run_eval.py --all`) is unblocked and recommended as the next
quota expenditure. Video remains untouched (zero credits spent in this pass).
