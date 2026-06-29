# Stress-test reference garments

This directory holds the **21 adversarial garment images** used by
`eval/stress_eval.py`.  They are not shipped in the repository because they are
third-party product photos whose licenses do not permit redistribution.

## How to populate

Each garment is described in
[`eval/stress_manifest.json`](../../stress_manifest.json) — the `name`,
`materials`, `construction`, and `hard_because` fields give enough detail to
find a visually equivalent reference image.

1. Source a product-shot JPEG for each of the 21 entries.
2. Save as `ref_01.jpeg` … `ref_21.jpeg` in this directory.
3. Run `python eval/stress_eval.py --all` to verify.

The naming must match the `ref` field in the manifest (`ref_01` → `ref_01.jpeg`).

> **Tip:** The garment descriptions are intentionally specific (e.g. "silk satin
> orchid-appliqué column gown" or "navy celestial-beaded mini dress") so that
> searching any fashion retailer by those terms will surface close equivalents.
