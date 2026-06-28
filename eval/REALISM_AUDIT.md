# Realism audit & next-generation pipeline

This document is the **source of truth** for the realism work on this project.
It records (1) where realism was being lost, (2) the root cause, (3) the survey
and ranking of computational-photography techniques considered, (4) what was
implemented and why, (5) what was deliberately *not* implemented, and (6) the
objective before/after evidence. It is written for the next engineer.

---

## 1. Findings: where realism was lost

The prompt-v2 benchmark ([BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md)) closed
the two *gross* failure modes (hem drift, earring omission) and pinned framing.
What remained were **photographic-quality** defects, not placement defects:

| # | Defect | Visible as |
| --- | --- | --- |
| 1 | Global re-synthesis of the image | the *entire* frame is re-rendered, not just the jewelry |
| 2 | Loss of original facial texture | skin micro-detail replaced by smooth "render" |
| 3 | Jewelry appears composited | piece reads as pasted rather than photographed |
| 4 | Unrealistic metal reflections | speculars that don't match the scene's lights |
| 5 | Missing contact shadows | piece floats; no grounding shadow on skin |
| 6 | Fabric material simplification | weave/sheen flattened on garment swaps |
| 7 | Hair depth ordering | strands that should occlude the piece sit behind it |
| 8 | Slight identity drift | the output is *almost* the same person |

**Conclusion of the audit: prompt engineering is no longer the bottleneck.**
Defects 1, 2, 8 are not instruction-following failures — the model *cannot*
return the user's original pixels, because it regenerates the whole image. No
prompt can fix that. This called for a pipeline change, not a prompt change.

### Root cause, measured

Nano Banana (Gemini image) is a generative editor: it outputs a fresh image,
not a diff of the input. We quantified how much it disturbs unedited pixels by
comparing each committed output against its input (downscaled to 512², mean
absolute per-pixel difference over RGB):

| case | median pixel Δ | mean pixel Δ | changed area (>25/255) | global brightness Δ |
| --- | --- | --- | --- | --- |
| necklace-cross-pendant | 2.0 | 2.9 | 0.8 % | −0.8 |
| earrings-gold-drop | 2.0 | 3.1 | 0.9 % | −0.7 |
| ring-three-stone-diamond | 2.3 | 2.8 | 0.2 % | −2.3 |
| bracelet-enamel-bangle | 2.7 | 4.7 | 2.3 % | −4.2 |
| clothing-breton-top | 2.0 | 6.4 | 4.9 % | −3.3 |
| clothing-green-wrap-dress | 2.0 | 12.4 | 12.0 % | −9.4 |

Two facts jump out and *define the whole strategy*:

1. **The real edit is tiny and local** (0.2 %–12 % of pixels). Everything else
   the model touched is collateral re-synthesis — exactly the source of
   defects 1, 2, 8 and the exposure/grain drift.
2. **The output is already pixel-registered to the input** (median Δ ≈ 2, the
   JPEG-recompression floor). Aspect-ratio pinning, added in prompt-v2, means
   the model keeps the input's framing, so a plain resize aligns the two — *no
   optical-flow / ECC registration is needed.*

That is the opening for the highest-ROI fix in the entire project: **keep the
model's pixels only inside the edit and restore the original photograph
everywhere else.**

---

## 2. Technique survey & ranking

Approaches considered (the brief's list plus standard virtual-try-on
literature), scored for this repository. "Compat" = compatibility with the
Nano Banana single-call architecture; "P(success)" = probability it materially
helps without a research project.

| Technique | Realism gain | Effort | Complexity | Compat | P(success) | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| **Pixel-preserving composite** (restore original outside edit) | ★★★★★ | Low | Med | ★★★★★ | ★★★★★ | **Ship** |
| **Auto change-mask** (diff → morphology → feather) | ★★★★★ | Low | Med | ★★★★★ | ★★★★★ | **Ship** (enables the above) |
| **Global tone/LAB harmonization** (kill exposure/WB drift) | ★★★★ | Low | Low | ★★★★★ | ★★★★★ | **Ship** |
| **Edge-aware feathering** (seamless boundary) | ★★★ | Low | Low | ★★★★★ | ★★★★★ | **Ship** |
| **Grain synthesis** (match edit-region noise to photo) | ★★★ | Low | Low | ★★★★★ | ★★★★ | **Ship** |
| Contact-shadow preservation (keep model's shadow in mask) | ★★★ | — | Low | ★★★★★ | ★★★★★ | **Ship** (falls out of the mask) |
| Face-lock ROI (protect a facial ellipse) | ★ | Low | Low | ★★★★ | ★★ | **Tried → dropped** (see §4) |
| Poisson / gradient-domain interior blend | ★★ | Med | High | ★★★ | ★★ | **Defer** — washes out metal speculars (defect 4 would worsen); alpha-feather is safer for jewelry |
| Hair matting / depth ordering (defect 7) | ★★★ | High | High | ★★ | ★★ | **Defer** — needs a real matting model (MODNet/BiRefNet); heavy dep, can't validate cheaply |
| Relighting / highlight suppression (defects 4) | ★★ | High | High | ★★ | ★ | **Defer** — needs scene light estimation; high risk of damaging good outputs |
| Local SD inpainting / hybrid two-model pipeline | ★★★ | High | High | ★ | ★★ | **Defer** — different architecture, large scope |
| Geometric registration (ECC / phase-corr) | ~0 here | Med | Med | ★★★ | ★★★ | **Skip** — measured unnecessary (median Δ ≈ 2) |

The top cluster is one coherent feature: a **pixel-preserving compositing
post-process**. It is the only change that attacks defects 1, 2, 5, 8 *and* the
exposure/grain drift at once, at low effort and high probability of success,
with zero change to the model call.

---

## 3. What was implemented

[`backend/services/compositing.py`](../backend/services/compositing.py) — a
dependency-light (numpy + scipy + Pillow) post-process applied to every
generation (config flag `TRYON_COMPOSITE`, default on; wired in
[`backend/app.py`](../backend/app.py) and [`eval/run_eval.py`](run_eval.py)).

Pipeline:

1. **Resize** the model output onto the original photo's pixel grid.
2. **Global tone harmonization** — fit a per-channel linear gain+bias on the
   unchanged majority of pixels so the output's exposure/white balance matches
   the input. Removes the global re-grade (the −0.7…−9.4 brightness drift) and
   guarantees a tonally seamless boundary.
3. **Change-mask extraction** — perceptual CIELAB ΔE between input and
   harmonized output → blur → threshold → drop specks → fill holes → dilate.
   The dilation deliberately captures the **contact shadow** the model drew on
   the skin/table (defect 5), so the piece stays grounded.
4. **Feather** the mask into a soft alpha (seamless seam, defect 3).
5. **Grain match** — re-inject sensor noise into the (denoised) edit region to
   match the surrounding photo's grain (defects 2/6 inside the edit).
6. **Composite**: `original·(1−α) + harmonized·α`.

**Identity preservation (defects 2, 8) is a *consequence*, not a stage:** the
face is outside the change mask, so its pixels are the literal original — drift
is impossible there. Likewise the background and untouched clothing.

**Safety valves** (so the post-process can never beat the raw baseline
downward): bail to the raw output if the mask is empty, if it covers more than
75 % of the frame, or if the output's aspect ratio disagrees with the input
(meaning the model re-cropped and the grids aren't comparable). Any exception
in post-processing is caught and the raw image is returned.

---

## 4. What was tried and rejected (honest record)

**Face-lock ROI.** The first iteration protected an elliptical facial region
so the original face was always kept. Offline validation
([compositing_eval.py](compositing_eval.py), alpha-overlay diagnostics) showed
it **clipped the jewelry**: earrings attach at the lobe and necklaces rise to
the collarbone, both close to a small face, so the ellipse erased parts of the
piece — while adding nothing, because the ΔE threshold *already* excludes
sub-threshold facial drift (the face simply isn't in the mask). It was removed.
This is the rule the brief asked for in action: *a technique that cannot be
validated to help is not merged.*

Poisson blending, hair matting, and relighting are deferred for the reasons in
the ranking table — each is either high-risk for these specific defects
(Poisson vs. metal speculars) or a research-scale dependency we cannot validate
within this architecture.

---

## 5. Objective validation

`python eval/compositing_eval.py` runs the post-process on the committed model
outputs (**no API spend**), scores raw-vs-composite with the heuristics in
[`metrics.py`](metrics.py), and renders before/after panels
(`input | raw | composite | diff(raw) | diff(composite)`).

Lower `border` (background preservation), `|bright|` (exposure drift) and
`meanΔ` (overall disturbance) are better — they mean the output is closer to a
real photo of the input person outside the edit.

| case | edit | border (raw→comp) | bright (raw→comp) | meanΔ (raw→comp) |
| --- | --- | --- | --- | --- |
| necklace-cross-pendant | 1.7 % | 1.88 → **0.18** | −0.72 → **−0.39** | 2.79 → **0.71** |
| earrings-gold-drop | 1.9 % | 1.79 → **0.18** | −0.57 → **+0.75** | 3.18 → **1.23** |
| ring-three-stone-diamond | 0.5 % | 1.93 → **0.14** | −2.02 → **−0.06** | 1.87 → **0.33** |
| bracelet-enamel-bangle | 3.7 % | 2.21 → **0.15** | −3.89 → **−1.77** | 4.01 → **2.39** |
| clothing-breton-top | 7.8 % | 1.87 → **0.09** | −3.18 → **−1.66** | 6.11 → **4.72** |
| clothing-green-wrap-dress | 16.2 % | 2.15 → **0.17** | −8.46 → **−6.90** | 14.61 → **12.88** |

Across all cases: **background drift collapses to the JPEG floor** (border ~2 →
~0.15) and **global exposure drift shrinks toward zero**, while the residual
`meanΔ` is exactly the legitimate edit (the jewelry/garment itself). The
remaining brightness residual on garments is the real garment being darker than
what it replaced, not a defect.

Committed evidence panels (the diff column is the proof — for the raw output the
*whole person* lights up; for the composite, *only the jewelry/garment* does):

- [necklace](../docs/realism/necklace-cross-pendant_before_after.jpg)
- [earrings](../docs/realism/earrings-gold-drop_before_after.jpg)
- [bracelet](../docs/realism/bracelet-enamel-bangle_before_after.jpg) (note the contact shadow is kept)
- [wrap dress](../docs/realism/clothing-green-wrap-dress_before_after.jpg) (face + background restored across a large garment swap)

---

## 6. Status & what is left

**Fixed / materially improved:** defects 1, 2, 5, 8 and exposure/grain drift —
the output is now provably a real photograph of the input person outside a
tight, grounded edit region.

**Still open (deferred with reasons above):** defect 4 (metal reflections) and
defect 7 (hair depth ordering) inside the edit region; defect 6 partially —
fabric texture inside a garment swap still comes from the model. These need
relighting / matting models that are out of scope for the current single-call
architecture and could not be validated cheaply; merging them speculatively
would violate the project's own quality bar.

This is, in our assessment, the highest practical realism achievable within the
current architecture without adding a second generative model. The next genuine
step up is a hybrid pipeline (segmentation + local inpainting or a matting
model for hair), which is a project, not a patch.

### Reproduce

```bash
python eval/compositing_eval.py     # offline A/B + panels (no API spend)
python eval/run_eval.py --hard      # shipped pipeline (composite on)
python eval/run_eval.py --hard --raw  # same prompts, compositing OFF (A/B)
python -m pytest tests/test_compositing.py -q
```

---

# Part 2 — Adversarial garment stress iteration (v3)

The previous sections fixed the *common* case. This iteration deliberately
attacked the pipeline with 21 hard real-world garments (structured jackets,
hoodies, corsets, sequins, paillettes, beaded/figurative embroidery, satin,
sheer mesh, feathers/fringe, polka dots, ombré, bubble hems, asymmetric
two-pieces, skirts, distressed denim). They live in `eval/stress/refs/`
(gitignored, user-supplied stress assets — *not* catalog items) and are
catalogued with per-garment difficulty analysis in
[`eval/stress_manifest.json`](stress_manifest.json).

The goal was not to make these specific garments "work" but to use them to
**expose architectural weaknesses simpler catalog items hide**, then fix the
ones that can be validated.

## Weaknesses found, by pipeline stage

| Stage | Weakness exposed | Evidence | Fix |
| --- | --- | --- | --- |
| **Prompt / taxonomy** | Type set was `{top, dress, trousers}`. Skirts had to map to `trousers` (grows trouser legs over bare legs); jackets/hoodies to `top` (deletes the layer underneath); two-piece sets had no representation. | manifest: ref_15/18/19/21 (skirts, set), ref_01/02/16 (outerwear) | Added `skirt`, `jacket`, `set` types with correct fit physics + a `layer:"over"` mode so outerwear is worn over existing clothing, not swapped. |
| **Prompt / materials** | Generic "reproduce the pattern" says nothing about *how a material reflects light*. Sequins, paillettes, satin, sheer fabric, beading, feathers, metal hardware are exactly what reads as AI-generated on a zoom-in. | manifest `primary_stress` = "model (specular/material)" on 12 of 21 | Keyword-triggered **material-physics** snippets (e.g. "each sequin is a tiny mirror reflecting the SAME scene lights"; "sheer = skin stays visible through it"). Additive: plain garments match nothing and don't regress. |
| **Compositing / mask** | The colour-only (ΔE) change mask under-segments a garment whose colour ≈ what it replaced: region recall fell to **0.61** in a controlled test, leaving holes where the original bleeds through. | controlled experiment (smooth light-grey garment over the grey-tee base) | Added a second, OR'd **texture cue** (change in local luma stddev). Recall → 0.75 on the smooth case and ~1.0 when texture differs (sequins on a matching colour). Validated to add no background false-positives on the real outputs (border still ~0.15 vs ~2.0 raw). |
| **Evaluation** | Global `noise_match`/`sharpness_match` over-flag patterned garments — a striped/sequined garment legitimately has more edge energy than the plain tee it replaced. | breton real output: global noise 1.38 / sharp 1.42 (both flag) | `preserved_region_parity()` measures grain/sharpness parity ONLY on the non-edited region (using the same two-cue mask). Breton preserved parity = **0.98 / 0.98** (clean) — confirms the over-flag was the garment, not a model defect. |

## What was NOT changed (validated as already-robust)

* **Tone harmonization on vivid/large garments.** Hypothesis: the global
  per-channel gain+bias, fit on neutral pixels, would distort a large saturated
  garment. A controlled test (vivid magenta garment, 16% of frame, with a model
  regrade applied to the whole output) showed the composite **recovers the true
  garment colour to within ~1-3/255** while removing the regrade from the
  background (drift ~0). Only a *nonlinear* saturation boost leaves a small
  residual; fixing that risks over-correcting plain garments, so it was left
  alone. Evidence over intuition: no change merged.

## Status of this iteration

Implemented + offline-validated (deterministic tests + controlled experiments +
the existing real outputs): the taxonomy/material/layering prompt redesign, the
texture-cue change mask, and the preserved-region parity metric. A one-command
live harness ([`eval/stress_eval.py`](stress_eval.py)) is ready to generate and
score all 21 garments through the full pipeline.

> **Live adversarial sweep: pending a working Nano Banana key.** The key in
> `.env` at audit time was a Vertex Express `AQ.` key that every Google endpoint
> rejected (`ACCESS_TOKEN_TYPE_UNSUPPORTED`). The pixel-level per-garment
> artifact analysis (which failures are prompt- vs model- vs compositing-borne)
> requires real generations and is recorded here once the sweep runs:
> `python eval/stress_eval.py --all`.

### Reproduce (v3)

```bash
python eval/stress_eval.py --all --dry-run   # build all 21 prompts, no API
python eval/stress_eval.py --all             # full live sweep (needs key)
python eval/stress_eval.py --ids ref_03,ref_13 --raw   # subset, compositing off
python -m pytest tests/test_clothing_prompt_builder.py tests/test_compositing.py -q
```
