# Failure gallery

Known failure modes of the try-on pipeline, with evidence and current status.
New flagged outputs from evaluation runs are copied into `eval/failures/`
automatically by `run_eval.py`; document notable ones here.

Heuristic metrics (see `eval/metrics.py`) flag suspects; entries below are
human-confirmed.

---

## FM-A · Garment hem drift (midi → maxi) + leg erasure

- **Evidence:** [docs/demo/result_wrap_dress.jpg](../docs/demo/result_wrap_dress.jpg) —
  the Emerald Wrap *Midi* Dress rendered noticeably longer than the product
  photo; on a separate real-user photo the same item rendered floor-length and
  the wearer's legs/hosiery were replaced by fabric entirely.
- **Root cause:** prompt loophole ("unless the garment naturally covers them")
  plus a catalog description that conflicted with the product photo's actual
  hem length; no body-landmark constraint existed.
- **Status:** **fixed — benchmark-verified** (run `20260611-054604`): hem at
  the lower calf, ankles and shoes visible, `lower_skin_ratio 1.03`. See
  [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md). The `lower_skin_ratio` metric
  guards against regression.

## FM-B · Earring omission under hair occlusion

- **Evidence:** [docs/demo/result_earrings.jpg](../docs/demo/result_earrings.jpg) —
  only one earring rendered; the other ear is covered by hair and received
  nothing, with no explanation to the user.
- **Root cause:** the v1 prompt permitted occlusion but gave the model no rule
  for *how conservative* to be, and the UI never warned the user that hidden
  ears can't take earrings.
- **Status:** **fixed — benchmark-verified** (run `20260611-054604`): with the
  v2 strict occlusion rules, both earrings now render, each emerging
  realistically below the hair, with no invented anatomy
  ([docs/demo/result_earrings_v2.jpg](../docs/demo/result_earrings_v2.jpg)).
  The UI additionally warns when an earrings item is selected. A fully hidden
  ear still correctly receives no earring — that remains by design.

## FM-C · Identity / lighting collapse on the older model generation

- **Evidence:** observed on a real-user photo (not committed — personal image):
  `gemini-2.5-flash-image` darkened a bright indoor portrait by roughly 40
  luma units, narrowed the face, and changed the framing. Same request on
  `gemini-3.1-flash-image` preserved identity, lighting and background.
- **Root cause:** model-generation limitation, not prompt.
- **Status:** default model switched to `gemini-3.1-flash-image`;
  `brightness_drift`, `border_preservation` and `noise_match` metrics exist to
  catch this class automatically if the model regresses.

## FM-D · "AI gloss" — garment cleaner than the photograph

- **Evidence:** the wrap-dress output above: fabric rendered with smooth,
  evenly-lit studio shading while the surrounding photo has flash falloff and
  sensor noise.
- **Root cause:** v1 prompts said "preserve the lighting" but never named the
  photographic properties (flash character, grain, sharpness, white balance).
- **Status:** addressed in prompt v2 (photographic-character section);
  `noise_match` / `sharpness_match` watch for regressions. Not fully
  eliminable — single-pass editing models have a smoothing bias.
