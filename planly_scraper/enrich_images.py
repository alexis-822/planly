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
import json, os, sys, io, time, base64, requests, tempfile, argparse, logging, re, hashlib
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
MIN_SIDE_PX = 600    # côté minimum en pixels (en dessous = rejeté)
MAX_RATIO   = 2.8    # ratio max largeur/hauteur (au dessus = trop aplati)

# Domaines avec watermarks commerciaux — toujours rejetés
WATERMARK_DOMAINS = [
    "alamy.com", "123rf.com", "shutterstock.com", "gettyimages.",
    "dreamstime.com", "depositphotos.com", "fotolia.com", "istockphoto.com",
    "stock.adobe", "pond5.com", "bigstockphoto.com",
]

def is_watermarked(url: str) -> bool:
    return any(d in url.lower() for d in WATERMARK_DOMAINS)

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
        "search_param": "tbs=isz:xl,itp:photo,ic:color",
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
                        if url and not is_watermarked(url) and (w == 0 or w >= 600):
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
        # Rejeter watermarks connus
        if is_watermarked(url):
            os.unlink(tmp.name)
            return None
        # Filtrer taille et ratio
        try:
            from PIL import Image as _PILCheck
            with open(tmp.name, "rb") as f:
                _w, _h = _PILCheck.open(f).size
            _min = min(_w, _h)
            _ratio = max(_w, _h) / _min if _min else 999
            if _min < MIN_SIDE_PX or _ratio > MAX_RATIO:
                os.unlink(tmp.name)
                return None
        except Exception:
            pass  # si Pillow échoue, on garde l'image
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

Note cette image de 1 à 5. Sois TRÈS STRICT sur la netteté :
5 = Photo parfaitement nette, lumineuse, très représentative du lieu
4 = Bonne photo nette, défauts mineurs acceptables
3 = Photo correcte mais qualité limitée
2 = Floue (même légèrement), sombre, mal cadrée, peu représentative, ou similaire à une autre photo du même lieu
1 = Plan/carte/screenshot/logo/texte/hors-sujet total

IMPORTANT : Si l'image est floue, même légèrement → is_blurry:true et score ≤ 2.
Si l'image ressemble à une photo déjà vue du même endroit → score ≤ 2.

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

    # Images existantes déjà téléchargées — filtrées (watermark, taille, ratio, doublons)
    existing_local = [p for p in (poi.get("photos") or []) if not p.startswith("http")]
    seen_existing_hashes = set()
    for i, local in enumerate(existing_local):
        full = os.path.join(SCRIPT_DIR, local)
        if not os.path.exists(full):
            continue
        url = existing_urls[i] if i < len(existing_urls) else ""
        # Rejeter watermarks connus
        if is_watermarked(url):
            log.info(f"    [existing] ✗ watermark — {url[:60]}")
            continue
        # Rejeter si taille insuffisante ou ratio aplati
        try:
            from PIL import Image as _PIL
            _w, _h = _PIL.open(full).size
            _min = min(_w, _h)
            _ratio = max(_w, _h) / _min if _min else 999
            if _min < MIN_SIDE_PX:
                log.info(f"    [existing] ✗ trop_petit({_w}x{_h}) — {os.path.basename(full)}")
                continue
            if _ratio > MAX_RATIO:
                log.info(f"    [existing] ✗ trop_aplati({_w}x{_h} ratio={_ratio:.1f}) — {os.path.basename(full)}")
                continue
        except Exception:
            pass
        # Rejeter doublons entre existantes
        try:
            with open(full, "rb") as _f:
                _h_val = hashlib.md5(_f.read()).hexdigest()
            if _h_val in seen_existing_hashes:
                log.info(f"    [existing] ✗ doublon — {os.path.basename(full)}")
                continue
            seen_existing_hashes.add(_h_val)
        except Exception:
            pass
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
    seen_hashes = set()  # déduplication par contenu

    for cand in all_candidates:
        tmp_path = cand.get("local")
        is_temp  = False
        if tmp_path is None:
            tmp_path = download_to_temp(cand["url"])
            is_temp  = True
            if tmp_path is None:
                log.info(f"    ✗ Impossible de télécharger {cand['url'][:60]}")
                continue

        # Dédup par hash fichier
        with open(tmp_path, "rb") as f:
            h = hashlib.md5(f.read()).hexdigest()
        if h in seen_hashes:
            log.info(f"    ✗ Doublon (même image) — {cand['url'][:60]}")
            if is_temp and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            continue
        seen_hashes.add(h)

        # 3. Score Claude Haiku
        result = score_image(name, subcat, tmp_path)
        score     = result.get("score", 1)
        is_map    = result.get("is_map", False)
        is_blurry = result.get("is_blurry", False)
        raison    = result.get("raison", "")
        log.info(f"    score={score} map={is_map} blur={is_blurry} — {raison[:55]} | {cand['url'][:45]}")

        # Cartes/plans = toujours rejetées ; le reste est gardé avec son score
        if is_map or score < 1:
            if is_temp and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            continue

        scored.append({"score": score, "path": tmp_path, "url": cand["url"],
                       "is_temp": is_temp, "source": cand["source"],
                       "is_blurry": is_blurry})

    # Trier : bonnes images (score≥MIN_SCORE, non floues) en premier, reste ensuite
    good    = [x for x in scored if x["score"] >= MIN_SCORE and not x["is_blurry"]]
    fallback = [x for x in scored if x not in good]
    good.sort(key=lambda x: -x["score"])
    fallback.sort(key=lambda x: -x["score"])

    # Toujours viser MAX_PHOTOS : bonnes en priorité, fallback pour compléter
    selected = (good + fallback)[:MAX_PHOTOS]

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

    n_good = sum(1 for s in selected if s["score"] >= MIN_SCORE and not s.get("is_blurry"))
    log.info(f"  [{tag}] ✓ {len(final_paths)} photos ({n_good} bonnes, {len(final_paths)-n_good} fallback) scores={[s['score'] for s in selected]}")
    return final_paths, final_urls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--poi", help="Traiter un ou plusieurs POIs (tags séparés par virgule)")
    parser.add_argument("--skip-fetch", action="store_true", help="Ne pas re-fetcher DataForSEO")
    args = parser.parse_args()

    with open(GLOBAL_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Filtrer si --poi (liste séparée par virgules)
    targets = data
    if args.poi:
        ids = [x.strip() for x in args.poi.split(",")]
        targets = [p for p in data if p["id"] in ids or p.get("name") in ids]
        if not targets:
            log.error(f"Aucun POI trouvé pour '{args.poi}'")
            return
        log.info(f"Cibles : {[p['name'] for p in targets]}")

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
