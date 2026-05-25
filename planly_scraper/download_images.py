"""
download_images.py — Télécharge les images des POIs avec pipeline qualité complet.

Pipeline par image :
1. Watermark URL check
2. Téléchargement
3. Magic bytes validation
4. Géométrie (taille min, ratio max)
5. Conversion WebP/PNG → JPEG
6. Resize max 1920px
7. MD5 dedup (intra-POI)
8. pHash dedup perceptuel (intra-POI)
"""
import json, os, re, requests, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
GLOBAL_JSON = os.path.join(SCRIPT_DIR, "output_global.json")
OUTPUT_DIR  = os.path.join(SCRIPT_DIR, "output")
IMAGES_DIR  = os.path.join(SCRIPT_DIR, "images")

from image_utils import (
    is_watermarked, check_geometry, normalize_to_jpeg, resize_if_needed,
    md5, is_perceptual_duplicate,
)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
TARGET_WIDTH = 1920


def upgrade_google_url(url):
    url = re.sub(r"=w\d+-h\d+-k-no", f"=w{TARGET_WIDTH}-h1080-k-no", url)
    url = re.sub(r"=s\d+", f"=s{TARGET_WIDTH}", url)
    return url


def download_raw(url, dest_path) -> tuple[bool, str]:
    try:
        if "googleusercontent.com" in url:
            url = upgrade_google_url(url)
        r = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return True, f"{os.path.getsize(dest_path) // 1024}KB"
    except Exception as e:
        return False, str(e)[:80]


def main():
    with open(GLOBAL_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    total, ok, fail, skip = 0, 0, 0, 0

    for poi in data:
        tag     = poi["id"]
        poi_dir = os.path.join(IMAGES_DIR, tag)
        os.makedirs(poi_dir, exist_ok=True)

        urls = []
        if poi.get("main_image"):
            urls.append(("main", poi["main_image"]))
        for i, url in enumerate(poi.get("photos", [])):
            urls.append((f"photo_{i+1}", url))

        if not urls:
            continue

        seen_md5    = set()
        seen_phash  = []
        new_photos  = []
        new_main    = None

        for label, url in urls:
            total += 1

            # 1. Watermark check avant même de télécharger
            if is_watermarked(url):
                print(f"  [{tag}] {label} SKIP watermark")
                skip += 1
                continue

            dest = os.path.join(poi_dir, f"{label}.jpg")

            # Si déjà téléchargé et valide, vérifier et appliquer les filtres manquants
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                ok_geom, raison = check_geometry(dest)
                if not ok_geom:
                    print(f"  [{tag}] {label} REJET {raison} — re-download")
                    os.unlink(dest)
                else:
                    h = md5(dest)
                    if h in seen_md5:
                        print(f"  [{tag}] {label} SKIP doublon_md5")
                        skip += 1
                        continue
                    seen_md5.add(h)
                    if is_perceptual_duplicate(dest, seen_phash):
                        print(f"  [{tag}] {label} SKIP doublon_perceptuel")
                        skip += 1
                        continue
                    print(f"  [{tag}] {label} SKIP (existe, valide)")
                    ok += 1
                    rel_path = f"images/{tag}/{label}.jpg"
                    if label == "main":
                        new_main = rel_path
                    new_photos.append(rel_path)
                    continue

            # Téléchargement
            tmp_path = dest + ".tmp"
            success, info = download_raw(url, tmp_path)
            if not success:
                print(f"  [{tag}] {label} FAIL: {info}")
                fail += 1
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                continue

            if os.path.getsize(tmp_path) < 10000:
                print(f"  [{tag}] {label} REJET trop_leger")
                os.remove(tmp_path)
                fail += 1
                continue

            # Magic bytes validation
            with open(tmp_path, "rb") as f:
                header = f.read(12)
            is_img = (header[:2] == b"\xff\xd8" or header[:4] == b"\x89PNG"
                      or header[:4] == b"RIFF" or b"WEBP" in header[:12])
            if not is_img:
                print(f"  [{tag}] {label} REJET pas_image")
                os.remove(tmp_path)
                fail += 1
                continue

            # Géométrie
            ok_geom, raison = check_geometry(tmp_path)
            if not ok_geom:
                print(f"  [{tag}] {label} REJET {raison}")
                os.remove(tmp_path)
                fail += 1
                continue

            # Conversion → JPEG + rename à dest
            try:
                final = normalize_to_jpeg(tmp_path)
                if final != dest:
                    os.rename(final, dest)
            except Exception as e:
                print(f"  [{tag}] {label} REJET conversion_fail: {e}")
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                fail += 1
                continue

            # Resize
            try:
                resize_if_needed(dest)
            except Exception:
                pass

            # MD5 dedup
            h = md5(dest)
            if h in seen_md5:
                print(f"  [{tag}] {label} REJET doublon_md5")
                os.remove(dest)
                skip += 1
                continue
            seen_md5.add(h)

            # pHash dedup
            if is_perceptual_duplicate(dest, seen_phash):
                print(f"  [{tag}] {label} REJET doublon_perceptuel")
                os.remove(dest)
                skip += 1
                continue

            from PIL import Image
            w, h_px = Image.open(dest).size
            print(f"  [{tag}] {label} OK ({info}, {w}x{h_px})")
            ok += 1
            time.sleep(0.2)

            rel_path = f"images/{tag}/{label}.jpg"
            if label == "main":
                new_main = rel_path
            new_photos.append(rel_path)

        # Mise à jour JSON
        if new_main:
            poi["main_image"] = new_main
        poi["photos_original_urls"] = poi.get("photos", [])
        poi["photos"] = new_photos

    with open(GLOBAL_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    for poi in data:
        tag = poi["id"]
        poi_path = os.path.join(OUTPUT_DIR, f"{tag}.json")
        if os.path.exists(poi_path):
            with open(poi_path, "w", encoding="utf-8") as f:
                json.dump(poi, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {ok} OK, {fail} fail, {skip} skip / {total} total")


if __name__ == "__main__":
    main()
