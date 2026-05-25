"""
enrich_images.py — Pipeline qualité images pour tous les POIs.

Pour chaque POI :
1. Récupère de nouveaux candidats via DataForSEO SERP Images (grandes photos couleur)
2. Combine avec les images existantes
3. Score chaque candidat avec Claude Haiku Vision (flou, plan/carte, pertinence)
4. Garde les 3 meilleures, télécharge en local, met à jour output_global.json

Usage : python enrich_images.py [--poi TAG] [--skip-fetch]
  --poi TAG       : traiter un seul POI (par son tag/id)
  --skip-fetch    : ne pas re-fetcher DataForSEO, utiliser uniquement les existantes
"""
import json, os, sys, io, time, base64, requests, tempfile, argparse, logging, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL_EXTRACT,
    DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD, DATAFORSEO_BASE_URL,
    BATCH_SIZE, IMAGE_DEPTH
)

GLOBAL_JSON = os.path.join(SCRIPT_DIR, "output_global.json")
IMAGES_DIR  = os.path.join(SCRIPT_DIR, "images")
MAX_PHOTOS  = 3
MAX_CANDIDATES = 10  # candidats max à scorer par POI
MIN_SCORE   = 3      # score minimum pour garder une image

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS_HTTP = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


# ── DataForSEO ──────────────────────────────────────────────────────────────

def _dfs_headers():
    creds = base64.b64encode(f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}


def fetch_image_candidates(pois: list[dict]) -> dict[str, list]:
    """Lance une recherche DataForSEO SERP Images pour chaque POI, retourne les candidats."""
    hdrs = _dfs_headers()

    # POST batch
    payload = [{
        "keyword": f"{p['name']} {p['commune']} photo",
        "location_name": "France",
        "language_code": "fr",
        "depth": IMAGE_DEPTH,
        "search_param": "tbs=isz:l,itp:photo,ic:color",
        "tag": p["id"],
    } for p in pois]

    log.info(f"POST images ({len(pois)} POIs)...")
    r = requests.post(f"{DATAFORSEO_BASE_URL}/serp/google/images/task_post",
                      json=payload, headers=hdrs, timeout=60)
    r.raise_for_status()
    data = r.json()

    tag_to_task = {}
    for task in (data.get("tasks") or []):
        tag = task.get("data", {}).get("tag")
        tid = task.get("id")
        if tag and tid:
            tag_to_task[tag] = tid

    log.info(f"Attente 30s...")
    time.sleep(30)

    results = {}
    for tag, tid in tag_to_task.items():
        candidates = []
        try:
            resp = requests.get(
                f"{DATAFORSEO_BASE_URL}/serp/google/images/task_get/advanced/{tid}",
                headers=hdrs, timeout=30
            )
            resp.raise_for_status()
            rdata = resp.json()
            for task2 in (rdata.get("tasks") or []):
                for res in (task2.get("result") or []):
                    for item in (res.get("items") or []):
                        url = item.get("source_url") or item.get("image_url")
                        w   = item.get("width") or 0
                        h   = item.get("height") or 0
                        if url and (w == 0 or w >= 600):
                            candidates.append({"url": url, "width": w, "height": h,
                                               "title": item.get("title", "")})
                        if len(candidates) >= MAX_CANDIDATES:
                            break
            log.info(f"  [{tag}] {len(candidates)} candidats DataForSEO")
        except Exception as e:
            log.warning(f"  [{tag}] erreur fetch: {e}")
        results[tag] = candidates

    return results


# ── Téléchargement temporaire ────────────────────────────────────────────────

def download_to_temp(url: str) -> str | None:
    """Télécharge une image dans un fichier temporaire, retourne le chemin ou None."""
    try:
        r = requests.get(url, headers=HEADERS_HTTP, timeout=15, stream=True)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if "image" not in ct and not any(url.lower().endswith(e) for e in (".jpg",".jpeg",".png",".webp")):
            return None
        suffix = ".jpg"
        for ext in (".png", ".webp", ".jpeg"):
            if ext in url.lower() or ext.replace(".", "") in ct:
                suffix = ext; break
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        for chunk in r.iter_content(8192):
            tmp.write(chunk)
        tmp.close()
        size = os.path.getsize(tmp.name)
        if size < 10000:  # < 10KB = trop petit
            os.unlink(tmp.name)
            return None
        # Vérifier que c'est bien une image (magic bytes)
        with open(tmp.name, "rb") as f:
            header = f.read(12)
        is_img = (
            header[:2] == b'\xff\xd8' or  # JPEG
            header[:4] == b'\x89PNG' or   # PNG
            header[:4] in (b'RIFF', b'WEBP') or  # WebP
            b'WEBP' in header[:12]
        )
        if not is_img:
            os.unlink(tmp.name)
            return None
        return tmp.name
    except Exception:
        return None


def image_to_base64(path: str) -> tuple[str, str]:
    """Retourne (base64_data, media_type). Redimensionne si > 4MB."""
    ext = os.path.splitext(path)[1].lower()
    mt = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
          "png": "image/png", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")
    with open(path, "rb") as f:
        data = f.read()
    # Claude limite à 5MB — si trop grand, redimensionner avec Pillow
    if len(data) > 4 * 1024 * 1024:
        try:
            from PIL import Image as PILImage
            import io as _io
            img = PILImage.open(_io.BytesIO(data))
            img.thumbnail((1920, 1920), PILImage.LANCZOS)
            buf = _io.BytesIO()
            fmt = "JPEG" if mt == "image/jpeg" else ("PNG" if mt == "image/png" else "JPEG")
            img.save(buf, format=fmt, quality=85)
            data = buf.getvalue()
            mt = "image/jpeg" if fmt == "JPEG" else mt
        except Exception:
            pass  # Si Pillow échoue, on tente quand même
    return base64.standard_b64encode(data).decode(), mt


# ── Claude Haiku Vision ──────────────────────────────────────────────────────

import anthropic

_client = None
def _claude():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


SCORE_PROMPT = """Tu analyses une photo pour l'application touristique Planly (Vendée, France).
POI : {poi_name} ({subcategory})

Note cette image de 1 à 5 :
5 = Photo nette, belle, lumineuse, très représentative du lieu
4 = Bonne photo, quelques défauts mineurs
3 = Photo acceptable mais pas idéale
2 = Floue, sombre, mal cadrée, ou peu représentative
1 = Plan/carte/screenshot/logo/texte/intérieur générique/totalement hors-sujet

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{"score": X, "raison": "...", "is_map": true/false, "is_blurry": true/false}}"""


def _parse_json_response(raw: str) -> dict:
    """Extrait un objet JSON d'une réponse Claude (avec ou sans backticks markdown)."""
    raw = raw.strip()
    # Strip markdown code blocks (```json ... ``` ou ``` ... ```)
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback : chercher le premier objet JSON dans le texte
        m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def score_image(poi_name: str, subcategory: str, img_path: str) -> dict:
    """Score une image avec Claude Haiku Vision. Retourne dict avec score 1-5."""
    try:
        b64, mt = image_to_base64(img_path)
        msg = _claude().messages.create(
            model=CLAUDE_MODEL_EXTRACT,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}},
                    {"type": "text", "text": SCORE_PROMPT.format(poi_name=poi_name, subcategory=subcategory)},
                ]
            }]
        )
        raw = msg.content[0].text.strip()
        return _parse_json_response(raw)
    except Exception as e:
        log.warning(f"    Score erreur: {e}")
        return {"score": 2, "raison": "erreur", "is_map": False, "is_blurry": False}


# ── Pipeline principal ───────────────────────────────────────────────────────

def process_poi(poi: dict, new_candidates: list) -> list[str]:
    """
    Évalue tous les candidats (existants + nouveaux) pour un POI.
    Retourne la liste des chemins locaux des 3 meilleures images.
    """
    tag        = poi["id"]
    name       = poi["name"]
    subcat     = poi.get("subcategory", "")
    poi_dir    = os.path.join(IMAGES_DIR, tag)
    os.makedirs(poi_dir, exist_ok=True)

    # 1. Candidats : images existantes + nouvelles URLs DataForSEO
    existing_urls = poi.get("photos_original_urls") or []
    all_candidates = []

    # Images existantes déjà téléchargées
    existing_local = [p for p in (poi.get("photos") or []) if not p.startswith("http")]
    for i, local in enumerate(existing_local):
        full = os.path.join(SCRIPT_DIR, local)
        if os.path.exists(full):
            url = existing_urls[i] if i < len(existing_urls) else ""
            all_candidates.append({"url": url, "local": full, "source": "existing"})

    # Nouveaux candidats DataForSEO
    seen_urls = {c["url"] for c in all_candidates}
    for cand in new_candidates:
        if cand["url"] not in seen_urls:
            all_candidates.append({"url": cand["url"], "local": None, "source": "new"})
            seen_urls.add(cand["url"])
        if len(all_candidates) >= MAX_CANDIDATES + len(existing_local):
            break

    log.info(f"  [{tag}] {len(all_candidates)} candidats total ({len(existing_local)} existants + {len(new_candidates)} nouveaux)")

    # 2. Télécharger les nouveaux candidats dans des fichiers temp
    scored = []
    for cand in all_candidates:
        tmp_path = cand.get("local")
        is_temp  = False
        if tmp_path is None:
            tmp_path = download_to_temp(cand["url"])
            is_temp  = True
            if tmp_path is None:
                log.info(f"    ✗ Impossible de télécharger {cand['url'][:60]}")
                continue

        # 3. Score Claude Haiku
        result = score_image(name, subcat, tmp_path)
        score  = result.get("score", 1)
        is_map = result.get("is_map", False)
        raison = result.get("raison", "")
        log.info(f"    score={score} map={is_map} — {raison[:60]} | {cand['url'][:50]}")

        if is_map or score < MIN_SCORE:
            if is_temp and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            continue

        scored.append({"score": score, "path": tmp_path, "url": cand["url"],
                       "is_temp": is_temp, "source": cand["source"]})

    # Trier par score desc
    scored.sort(key=lambda x: -x["score"])
    selected = scored[:MAX_PHOTOS]

    if not selected:
        log.warning(f"  [{tag}] Aucune image valide ! Conservation des existantes.")
        return poi.get("photos") or []

    # 4. Sauvegarder les sélectionnées dans images/{tag}/
    import shutil

    def _safe_copy(src: str, dst: str):
        """Copie robuste sur Windows (évite WinError 32 si fichier ouvert)."""
        # Normaliser les chemins pour comparer (Windows : / vs \, casse)
        if os.path.normcase(os.path.normpath(src)) == os.path.normcase(os.path.normpath(dst)):
            return
        try:
            shutil.copy2(src, dst)
        except PermissionError:
            with open(src, "rb") as f:
                data = f.read()
            with open(dst, "wb") as f:
                f.write(data)

    final_paths = []
    final_urls  = []
    for i, item in enumerate(selected, 1):
        ext      = os.path.splitext(item["path"])[1] or ".jpg"
        dest     = os.path.join(poi_dir, f"photo_{i}{ext}")
        rel_path = f"images/{tag}/photo_{i}{ext}"

        if item["source"] == "existing" and not item["is_temp"]:
            _safe_copy(item["path"], dest)
        else:
            try:
                shutil.move(item["path"], dest)
            except PermissionError:
                with open(item["path"], "rb") as f:
                    data = f.read()
                with open(dest, "wb") as f:
                    f.write(data)

        final_paths.append(rel_path)
        final_urls.append(item["url"])

    # Nettoyer les anciens fichiers non retenus — normaliser les chemins (Windows / vs \)
    dest_fulls = {os.path.normcase(os.path.normpath(os.path.join(poi_dir, os.path.basename(p))))
                  for p in final_paths}
    for f in os.listdir(poi_dir):
        fpath = os.path.normcase(os.path.normpath(os.path.join(poi_dir, f)))
        if fpath not in dest_fulls:
            try:
                os.unlink(os.path.join(poi_dir, f))
            except Exception:
                pass

    # Nettoyer les temps restants non utilisés
    for item in scored[MAX_PHOTOS:]:
        if item["is_temp"] and os.path.exists(item["path"]):
            try:
                os.unlink(item["path"])
            except Exception:
                pass

    log.info(f"  [{tag}] ✓ {len(final_paths)} photos retenues (scores: {[s['score'] for s in selected]})")
    return final_paths, final_urls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--poi", help="Traiter un seul POI (tag/id)")
    parser.add_argument("--skip-fetch", action="store_true", help="Ne pas re-fetcher DataForSEO")
    args = parser.parse_args()

    with open(GLOBAL_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Filtrer si --poi
    targets = data
    if args.poi:
        targets = [p for p in data if p["id"] == args.poi or p.get("name") == args.poi]
        if not targets:
            log.error(f"POI '{args.poi}' non trouvé")
            return

    # 1. Fetch DataForSEO pour tous les POIs cibles
    new_candidates_map = {}
    if not args.skip_fetch:
        log.info(f"=== Fetch DataForSEO pour {len(targets)} POIs ===")
        # Batch par 10
        for i in range(0, len(targets), BATCH_SIZE):
            batch = targets[i:i + BATCH_SIZE]
            candidates = fetch_image_candidates(batch)
            new_candidates_map.update(candidates)
            if i + BATCH_SIZE < len(targets):
                time.sleep(5)
    else:
        log.info("Skip fetch DataForSEO (--skip-fetch)")

    # 2. Scorer et sélectionner pour chaque POI
    log.info(f"\n=== Scoring Claude Vision pour {len(targets)} POIs ===")
    for poi in targets:
        tag = poi["id"]
        log.info(f"\n[{tag}] {poi['name']}")
        new_cands = new_candidates_map.get(tag, [])
        result = process_poi(poi, new_cands)
        if isinstance(result, tuple):
            final_paths, final_urls = result
        else:
            final_paths = result
            final_urls  = poi.get("photos_original_urls") or []

        poi["photos"] = final_paths
        poi["photos_original_urls"] = final_urls

    # 3. Sauvegarder
    with open(GLOBAL_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"\n✅ output_global.json mis à jour ({len(targets)} POIs traités)")
    log.info("Lance maintenant : python inject_pois.py && python ../fetch_tides.py")


if __name__ == "__main__":
    main()
