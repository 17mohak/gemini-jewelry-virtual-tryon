"""Provenance: builds the zoomed comparison strips + region metrics cited in
REALISM_AUDIT.md. Requires the gitignored eval/runs/ outputs of runs
20260611-070715 and 20260611-071658 to be present locally."""
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

ROOT = Path(__file__).resolve().parent.parent.parent
RUN = ROOT / "eval" / "runs" / "20260611-070715"
RUN2 = ROOT / "eval" / "runs" / "20260611-071658"
DEMO = ROOT / "docs" / "demo"
OUT = ROOT / "eval" / "audit"
OUT.mkdir(exist_ok=True)


def load(p):
    return Image.open(p).convert("RGB")


def crop_norm(im, box):
    """box in 0-1024 coords normalized to the image's actual size."""
    w, h = im.size
    x0, y0, x1, y1 = (box[0] * w // 1024, box[1] * h // 1024,
                      box[2] * w // 1024, box[3] * h // 1024)
    return im.crop((x0, y0, x1, y1))


def strip(name, panels, height=460):
    ims = []
    for im, box in panels:
        c = crop_norm(im, box)
        c = c.resize((int(c.width * height / c.height), height), Image.LANCZOS)
        ims.append(c)
    gap = 12
    total_w = sum(i.width for i in ims) + gap * (len(ims) - 1)
    canvas = Image.new("RGB", (total_w, height), (255, 255, 255))
    x = 0
    for i in ims:
        canvas.paste(i, (x, 0))
        x += i.width + gap
    canvas.save(OUT / f"{name}.jpg", quality=90)
    print("wrote", name, canvas.size)


face_in = load(DEMO / "input_face.jpg")
hand_in = load(DEMO / "input_hand.jpg")
body_in = load(DEMO / "input_body.jpg")

gemset = load(RUN / "necklace-gemset.jpg")
cross = load(RUN / "necklace-cross-pendant.jpg")
drop = load(RUN / "earrings-gold-drop.jpg")
hoop2 = load(RUN2 / "earrings-gold-hoop.jpg")
ring = load(RUN / "ring-three-stone-diamond.jpg")
bangle = load(RUN / "bracelet-enamel-bangle.jpg")
oxford = load(RUN / "clothing-white-oxford.jpg")
wrap = load(RUN / "clothing-green-wrap-dress.jpg")
jeans = load(RUN / "clothing-blue-jeans.jpg")
breton = load(RUN / "clothing-breton-top.jpg")

# 1. neck region: input vs gem-set vs cross (contact shadows, grain, color spill)
strip("01_neck_input_gemset_cross", [
    (face_in, (320, 560, 700, 1000)),
    (gemset, (320, 560, 700, 1000)),
    (cross, (320, 560, 700, 1000)),
])

# 2. earring zoom: input ear region vs drop vs hoop re-run (occlusion, attachment)
strip("02_ear_input_drop_hoop", [
    (face_in, (560, 380, 840, 760)),
    (drop, (560, 380, 840, 760)),
    (hoop2, (560, 380, 840, 760)),
])

# 3. ring zoom: input vs output (band-finger junction, shadow)
strip("03_ring_input_output", [
    (hand_in, (280, 280, 560, 500)),
    (ring, (280, 280, 560, 500)),
])

# 4. bracelet zoom: input vs output (wrist wrap, ellipse, contact)
strip("04_bracelet_input_output", [
    (hand_in, (200, 580, 740, 1010)),
    (bangle, (200, 580, 740, 1010)),
])

# 5. face identity: input body face vs oxford vs wrap (AI gloss)
strip("05_faces_input_oxford_wrap", [
    (body_in, (420, 20, 650, 240)),
    (oxford, (420, 20, 650, 240)),
    (wrap, (420, 20, 650, 240)),
], height=420)

# 6. fabric folds: wrap dress torso+skirt vs breton torso (fold logic, shading)
strip("06_fabric_wrap_breton", [
    (wrap, (360, 300, 700, 860)),
    (breton, (360, 180, 700, 740)),
])

# 7. ankles: input vs jeans (invented socks) vs wrap (hem boundary)
strip("07_ankles_input_jeans_wrap", [
    (body_in, (380, 820, 680, 1024)),
    (jeans, (380, 820, 680, 1024)),
    (wrap, (380, 820, 680, 1024)),
], height=380)


# region metrics: edge energy (grain+detail) and mean luma, per box
def region_stats(im, box):
    c = crop_norm(im, box).convert("L")
    edges = c.filter(ImageFilter.FIND_EDGES)
    return (ImageStat.Stat(edges).stddev[0], ImageStat.Stat(c).mean[0])

print("\nregion edge-stddev / mean-luma  (input -> output)")
checks = [
    ("gemset necklace box", face_in, gemset, (340, 600, 680, 960)),
    ("gemset wall box", face_in, gemset, (760, 80, 1000, 420)),
    ("gemset cheek box", face_in, gemset, (430, 330, 600, 500)),
    ("cross chain-skin box", face_in, cross, (360, 580, 660, 840)),
    ("ring finger box", hand_in, ring, (330, 300, 500, 460)),
    ("bangle wrist box", hand_in, bangle, (240, 620, 700, 980)),
    ("oxford shirt box", body_in, oxford, (400, 200, 660, 500)),
    ("oxford face box", body_in, oxford, (440, 40, 620, 200)),
    ("wrap skirt box", body_in, wrap, (380, 460, 660, 820)),
    ("wall box (body/wrap)", body_in, wrap, (700, 100, 980, 600)),
]
for name, a, b, box in checks:
    ea, la = region_stats(a, box)
    eb, lb = region_stats(b, box)
    print(f"  {name:24s} edge {ea:6.1f} -> {eb:6.1f}   luma {la:5.1f} -> {lb:5.1f}")
