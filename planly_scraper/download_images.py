"""Télécharge toutes les images des POIs et met à jour les JSON avec les chemins locaux."""
import json, os, requests, time, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GLOBAL_JSON = os.path.join(SCRIPT_DIR, "output_global.json")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
IMAGES_DIR = os.path.join(SCRIPT_DIR, "images")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def download_image(url, dest_path):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        # Determine extension from content type if needed
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        size_kb = os.path.getsize(dest_path) / 1024
        return True, f"{size_kb:.0f}KB"
    except Exception as e:
        return False, str(e)[:80]

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
                print(f"  [{tag}] {label} SKIP (exists)")
                ok += 1
            else:
                success, info = download_image(url, dest)
                if success:
                    print(f"  [{tag}] {label} OK ({info})")
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
