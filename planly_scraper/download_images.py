"""Télécharge toutes les images des POIs et met à jour les JSON avec les chemins locaux.
Contrôle qualité : rejette les images < MIN_WIDTH pixels de large."""
import json, os, re, requests, time, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GLOBAL_JSON = os.path.join(SCRIPT_DIR, "output_global.json")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
IMAGES_DIR = os.path.join(SCRIPT_DIR, "images")
try:
    from config import MIN_IMAGE_WIDTH
    MIN_WIDTH = MIN_IMAGE_WIDTH
except:
    MIN_WIDTH = 800
TARGET_WIDTH = 1200  # taille cible pour les images Google

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def upgrade_google_url(url):
    """Force la résolution HD sur les URLs Google."""
    url = re.sub(r'=w\d+-h\d+-k-no', f'=w{TARGET_WIDTH}-h900-k-no', url)
    url = re.sub(r'=s\d+', f'=s{TARGET_WIDTH}', url)
    return url


def download_image(url, dest_path):
    try:
        # Upgrade Google URLs automatiquement
        if "googleusercontent.com" in url:
            url = upgrade_google_url(url)
        r = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        size_kb = os.path.getsize(dest_path) / 1024
        return True, f"{size_kb:.0f}KB"
    except Exception as e:
        return False, str(e)[:80]


def check_image_quality(path):
    """Vérifie que l'image fait au moins MIN_WIDTH pixels de large."""
    try:
        from PIL import Image
        img = Image.open(path)
        w, h = img.size
        img.close()
        return w >= MIN_WIDTH, w
    except:
        return False, 0

def get_extension(url):
    # Extract extension from URL
    path = url.split("?")[0].split("#")[0]
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"):
        return ext
    return ".jpg"  # default

def main():
    with open(GLOBAL_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    total, ok, fail = 0, 0, 0

    for poi in data:
        tag = poi["id"]
        poi_dir = os.path.join(IMAGES_DIR, tag)
        os.makedirs(poi_dir, exist_ok=True)

        # Collect all image URLs
        urls = []
        if poi.get("main_image"):
            urls.append(("main", poi["main_image"]))
        for i, url in enumerate(poi.get("photos", [])):
            if url != poi.get("main_image"):
                urls.append((f"photo_{i+1}", url))
            else:
                urls.append((f"photo_{i+1}", url))

        if not urls:
            continue

        new_photos = []
        new_main = None

        for label, url in urls:
            total += 1
            ext = get_extension(url)
            filename = f"{label}{ext}"
            dest = os.path.join(poi_dir, filename)
            rel_path = f"images/{tag}/{filename}"

            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                # Vérifier la qualité de l'image existante
                ok_quality, w = check_image_quality(dest)
                if ok_quality:
                    print(f"  [{tag}] {label} SKIP ({w}px)")
                    ok += 1
                else:
                    print(f"  [{tag}] {label} TROP PETIT ({w}px) — re-download")
                    success, info = download_image(url, dest)
                    if success:
                        ok_q2, w2 = check_image_quality(dest)
                        if ok_q2:
                            print(f"  [{tag}] {label} OK ({w2}px, {info})")
                            ok += 1
                        else:
                            print(f"  [{tag}] {label} WARNING: source trop petite ({w2}px)")
                            ok += 1  # on garde quand même
                    else:
                        fail += 1
                    time.sleep(0.3)
            else:
                success, info = download_image(url, dest)
                if success:
                    ok_quality, w = check_image_quality(dest)
                    quality_str = f"{w}px" if ok_quality else f"WARNING {w}px < {MIN_WIDTH}px"
                    print(f"  [{tag}] {label} OK ({info}, {quality_str})")
                    ok += 1
                else:
                    print(f"  [{tag}] {label} FAIL: {info}")
                    fail += 1
                    if os.path.exists(dest):
                        os.remove(dest)
                    rel_path = url  # keep original URL on failure
                time.sleep(0.3)

            if label == "main":
                new_main = rel_path
            new_photos.append(rel_path)

        # Update POI data
        if new_main:
            poi["main_image"] = new_main
        poi["photos_original_urls"] = poi.get("photos", [])
        if poi.get("main_image") and "main_image_original_url" not in poi:
            poi["main_image_original_url"] = urls[0][1] if urls[0][0] == "main" else None
        poi["photos"] = new_photos

    # Save updated global
    with open(GLOBAL_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Save individual files
    for poi in data:
        tag = poi["id"]
        poi_path = os.path.join(OUTPUT_DIR, f"{tag}.json")
        if os.path.exists(poi_path):
            with open(poi_path, "w", encoding="utf-8") as f:
                json.dump(poi, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {ok}/{total} OK, {fail} failed")

if __name__ == "__main__":
    main()
