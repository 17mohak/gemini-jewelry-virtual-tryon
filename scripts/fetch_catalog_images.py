"""One-off helper used to source royalty-free catalog images from Wikimedia Commons.

Downloads candidate product photos (with license/attribution metadata) into
``scripts/_candidates`` so they can be reviewed by hand before being promoted
into ``backend/catalog/images``. Kept in the repo for provenance/reproducibility.

Usage:  python scripts/fetch_catalog_images.py
"""

import json
import pathlib
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "jewelry-tryon-assignment/1.0 (catalog image sourcing)"}
OUT = pathlib.Path(__file__).parent / "_candidates"

SEARCHES = {
    "necklace_pendant": "gold pendant necklace white background",
    "necklace_pearl": "pearl necklace jewelry white background",
    "earrings_stud": "diamond stud earrings",
    "earrings_hoop": "gold hoop earrings",
    "ring_diamond": "diamond ring white background",
    "ring_gold": "gold ring jewellery white background",
    "bracelet_bangle": "gold bangle bracelet",
    "bracelet_chain": "silver bracelet jewelry white background",
}


def search(term: str, limit: int = 6):
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {term}",
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": "900",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return list(data.get("query", {}).get("pages", {}).values())


def main():
    OUT.mkdir(exist_ok=True)
    manifest = {}
    for slug, term in SEARCHES.items():
        for i, page in enumerate(search(term)):
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("mime") not in ("image/jpeg", "image/png"):
                continue
            meta = info.get("extmetadata", {})
            thumb = info.get("thumburl") or info.get("url")
            name = f"{slug}_{i}.jpg"
            try:
                req = urllib.request.Request(thumb, headers=UA)
                (OUT / name).write_bytes(urllib.request.urlopen(req, timeout=30).read())
            except Exception as exc:  # noqa: BLE001 - best-effort candidate fetch
                print(f"skip {name}: {exc}")
                continue
            manifest[name] = {
                "title": page.get("title"),
                "source": info.get("descriptionurl"),
                "license": meta.get("LicenseShortName", {}).get("value"),
                "artist": meta.get("Artist", {}).get("value"),
            }
            print("saved", name, "|", manifest[name]["license"], "|", page.get("title"))
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
