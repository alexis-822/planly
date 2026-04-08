"""Re-télécharge toutes les images en haute résolution."""
import json, os, re, requests, sys, io, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GLOBAL_JSON = os.path.join(SCRIPT_DIR, "output_global.json")
IMAGES_DIR = os.path.join(SCRIPT_DIR, "images")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def upgrade_google_url(url):
    """Remplace les params de taille Google par une résolution max."""
    # =w408-h306-k-no → =w1600-h1200-k-no
    url = re.sub(r'=w\d+-h\d+-k-no', '=w1600-h1200-k-no', url)
    # =s408 → =s1600
    url = re.sub(r'=s\d+', '=s1600', url)
    return url


def download(url, dest):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return os.path.getsize(dest)
    except Exception as e:
        return 0


def main():
    with open(GLOBAL_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    upgraded = 0
    skipped = 0

    for poi in data:
        tag = poi["id"]
        originals = poi.get("photos_original_urls", [])
        photos = poi.get("photos", [])

        for i, orig_url in enumerate(originals):
            if i >= len(photos):
                break

            local_path = photos[i]
            if local_path.startswith("http"):
                continue  # Failed download, skip

            full_path = os.path.join(SCRIPT_DIR, local_path)
            current_size = os.path.getsize(full_path) if os.path.exists(full_path) else 0

            # Check actual resolution
            try:
                from PIL import Image
                img = Image.open(full_path)
                w, h = img.size
                img.close()
                if w >= 1400 and current_size > 150000:
                    skipped += 1
                    continue
            except:
                pass

            # Upgrade Google URL
            if "googleusercontent.com" in orig_url:
                hd_url = upgrade_google_url(orig_url)
            else:
                hd_url = orig_url  # Re-download non-Google as-is

            new_size = download(hd_url, full_path)
            if new_size > current_size:
                print(f"  [{tag}] photo_{i+1}: {current_size//1024}KB -> {new_size//1024}KB")
                upgraded += 1
            else:
                skipped += 1

            time.sleep(0.2)

    print(f"\nDone: {upgraded} upgraded, {skipped} already OK")


if __name__ == "__main__":
    main()
