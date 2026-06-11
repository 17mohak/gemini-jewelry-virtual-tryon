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
- **Status:** **fixed — verified catalog-wide** (hard subset run
  `20260611-054604`, then the full 15-case sweep `20260611-070715`): hem at
  the lower calf, ankles and shoes visible, `lower_skin_ratio ≥ 0.997` on all
  five clothing cases. See [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md). The
  `lower_skin_ratio` metric guards against regression.

## FM-B · Earring omission under hair occlusion

- **Evidence:** [docs/demo/result_earrings.jpg](../docs/demo/result_earrings.jpg) —
  only one earring rendered; the other ear is covered by hair and received
  nothing, with no explanation to the user.
- **Root cause:** the v1 prompt permitted occlusion but gave the model no rule
  for *how conservative* to be, and the UI never warned the user that hidden
  ears can't take earrings.
- **Status:** **fixed — benchmark-verified** (run `20260611-054604`, held in
  the full sweep `20260611-070715`): with the v2 strict occlusion rules, both
  earrings now render, each emerging realistically below the hair, with no
  invented anatomy
  ([docs/demo/result_earrings_v2.jpg](../docs/demo/result_earrings_v2.jpg)).
  The UI additionally warns when an earrings item is selected. A fully hidden
  ear still correctly receives no earring — that remains by design (the hoop
  re-run `20260611-071658` shows this conservatism: one visible ear got the
  hoop, the fully covered ear got nothing).

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
  eliminable — single-pass editing models have a smoothing bias. The full
  catalog sweep (`20260611-070715`) confirms the residual: all five clothing
  cases show mild face smoothing (identity scored 4/5), none severe. The
  sweep also recorded the *opposite* polarity once: the ornate gem-set
  necklace mildly **amplified** grain on the background wall (noise 1.32 vs
  the 1.30 limit — `eval/failures/20260611-070715_necklace-gemset.jpg`);
  borderline, reviewed acceptable.

## FM-E · Invented under-layers on garment swaps

- **Evidence:** full-sweep run `20260611-070715`: the Black A-Line Dress case
  replaced the input's opaque full-length leggings with sheer black tights
  below the knee-length hem; the jeans case added small white socks at the
  ankles where the input showed none. The realism audit
  ([REALISM_AUDIT.md](REALISM_AUDIT.md), crop `audit/07_ankles…`) confirmed a
  third variant at zoom: the wrap-dress case rendered *bare* lower legs where
  the input wore opaque leggings — so all three possible inventions (tights /
  socks / bare skin) occur, chosen unpredictably.
- **Root cause:** under-layer ambiguity, not a prompt bug: the dress swap
  legitimately removes the leggings, the product covers only to the knee, and
  the input had no bare lower-leg skin to preserve — so the model must invent
  *something* between hem and sneakers. Bare skin would violate the
  no-invented-skin rule; it picks a plausible under-layer instead.
- **Status:** **documented, deliberately not prompt-patched.** The outputs
  are cosmetically reasonable and anatomy-safe; a rule forcing any specific
  choice (keep leggings / render bare skin) would be wrong for other
  input-garment combinations. Revisit only if a real user case makes the
  invented layer objectionable.
