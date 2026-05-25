import base64
import logging
import time
import requests
from config import (
    DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD, DATAFORSEO_BASE_URL,
    BATCH_SIZE, TASK_WAIT_SECONDS, REVIEW_WAIT_SECONDS,
    REVIEW_DEPTH, IMAGE_DEPTH, MAX_PHOTOS,
)

log = logging.getLogger(__name__)


def _auth_header() -> dict:
    creds = base64.b64encode(f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}


HEADERS = None


def _headers():
    global HEADERS
    if HEADERS is None:
        HEADERS = _auth_header()
    return HEADERS


def _post(endpoint: str, payload: list[dict]) -> dict:
    url = f"{DATAFORSEO_BASE_URL}{endpoint}"
    resp = requests.post(url, json=payload, headers=_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json()


def _get(endpoint: str) -> dict:
    url = f"{DATAFORSEO_BASE_URL}{endpoint}"
    resp = requests.get(url, headers=_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json()


def _get_items(resp: dict) -> list:
    """Extrait les items d'une réponse DataForSEO (safe None handling)."""
    items = []
    for task in (resp.get("tasks") or []):
        for r in (task.get("result") or []):
            for item in (r.get("items") or []):
                items.append(item)
    return items


# ─────────────────────────────────────────────
# Keyword variants — retry logic
# ─────────────────────────────────────────────

def _maps_result_matches(poi_name: str, maps_title: str, maps_category: str = None) -> bool:
    """Vérifie que le résultat Maps correspond bien au POI recherché.

    Rejette les résultats qui sont clairement un autre type de lieu
    (ex: un camping quand on cherche une plage).
    """
    if not maps_title:
        return False

    title_lower = maps_title.lower()

    # Blacklist : catégories Google qui ne correspondent jamais à nos POIs
    WRONG_TYPES = ["camping", "hôtel", "hotel", "supermarché", "pharmacie",
                   "banque", "assurance", "immobilier", "auto-école", "garage"]
    for wrong in WRONG_TYPES:
        if wrong in title_lower and wrong not in poi_name.lower():
            return False

    # Vérifier aussi la catégorie Google Maps si disponible
    if maps_category:
        cat_lower = maps_category.lower()
        WRONG_CATS = ["camping", "hôtel", "hébergement", "supermarché", "pharmacie",
                      "banque", "assurance", "agence immobilière"]
        for wrong in WRONG_CATS:
            if wrong in cat_lower:
                return False

    # Mots significatifs du nom du POI (ignorer articles)
    skip = {"le", "la", "les", "l", "de", "du", "des", "d", "et", "&", "à"}
    poi_words = {w.lower() for w in poi_name.split() if w.lower() not in skip and len(w) > 2}
    # Au moins 1 mot significatif du POI doit être dans le titre Maps
    matches = sum(1 for w in poi_words if w in title_lower)
    return matches >= 1


def _keyword_variants(name: str, commune: str) -> list[str]:
    """Génère des variantes de keywords pour maximiser les chances de match."""
    variants = [f"{name} {commune}"]
    # Sans le premier mot si c'est un article/adjectif courant
    words = name.split()
    if len(words) > 2 and words[0].lower() in ("le", "la", "les", "l'", "grande", "grand", "petit", "petite"):
        variants.append(f"{' '.join(words[1:])} {commune}")
    # Nom seul + ville principale
    commune_short = commune.split(",")[0].strip()
    if commune_short != commune:
        variants.append(f"{name} {commune_short}")
    return variants


# ─────────────────────────────────────────────
# ÉTAPE 1 — my_business_info (avec retry par variantes)
# ─────────────────────────────────────────────

def _extract_business_data(item: dict) -> dict:
    rating = item.get("rating") or {}
    attrs = item.get("attributes") or {}
    return {
        "name_google": item.get("title"),
        "description_raw": item.get("description"),
        "lat": item.get("latitude"),
        "lng": item.get("longitude"),
        "address": item.get("address"),
        "address_info": item.get("address_info"),
        "phone": item.get("phone"),
        "website": item.get("url"),
        "domain": item.get("domain"),
        "rating": rating.get("value"),
        "reviews_count": rating.get("votes_count"),
        "rating_distribution": item.get("rating_distribution"),
        "opening_hours": (item.get("work_time") or {}).get("timetable"),
        "popular_times": item.get("popular_times"),
        "price_level": item.get("price_level"),
        "category_google": item.get("category"),
        "additional_categories": item.get("additional_categories"),
        "main_image": item.get("main_image"),
        "total_photos": item.get("total_photos"),
        "attributes_available": attrs.get("available_attributes"),
        "attributes_unavailable": attrs.get("unavailable_attributes"),
        "place_topics": item.get("place_topics"),
        "booking_url": item.get("local_business_links"),
        "cid": item.get("cid"),
        "place_id": item.get("place_id"),
    }


def _post_single_business(keyword: str, tag: str) -> str | None:
    """POST une seule task business_info, retourne le task_id."""
    payload = [{
        "keyword": keyword,
        "location_name": "France",
        "language_code": "fr",
        "tag": tag,
    }]
    result = _post("/business_data/google/my_business_info/task_post", payload)
    for task in (result.get("tasks") or []):
        return task.get("id")
    return None


def _fetch_single_business(task_id: str) -> dict | None:
    """GET un résultat business_info, retourne l'item extrait ou None."""
    resp = _get(f"/business_data/google/my_business_info/task_get/{task_id}")
    items = _get_items(resp)
    return _extract_business_data(items[0]) if items else None


def _search_maps_live(keyword: str) -> dict | None:
    """Recherche Google Maps Live — retourne les données du premier résultat."""
    payload = [{
        "keyword": keyword,
        "location_name": "France",
        "language_code": "fr",
        "depth": 1,
    }]
    result = _post("/serp/google/maps/live/advanced", payload)
    items = _get_items(result)
    if not items:
        return None
    item = items[0]
    rating = item.get("rating") or {}
    return {
        "name_google": item.get("title"),
        "description_raw": item.get("snippet"),
        "lat": item.get("latitude"),
        "lng": item.get("longitude"),
        "address": item.get("address"),
        "address_info": item.get("address_info"),
        "phone": item.get("phone"),
        "website": item.get("url") or item.get("domain"),
        "domain": item.get("domain"),
        "rating": rating.get("value") if isinstance(rating, dict) else None,
        "reviews_count": rating.get("votes_count") if isinstance(rating, dict) else None,
        "rating_distribution": item.get("rating_distribution"),
        "opening_hours": (item.get("work_time") or {}).get("timetable"),
        "popular_times": None,
        "price_level": item.get("price_level"),
        "category_google": item.get("category"),
        "additional_categories": item.get("additional_categories"),
        "main_image": item.get("main_image"),
        "total_photos": item.get("total_photos"),
        "attributes_available": None,
        "attributes_unavailable": None,
        "place_topics": None,
        "booking_url": None,
        "cid": item.get("cid"),
        "place_id": item.get("place_id"),
    }


def fetch_all_business(pois: list[dict], wait: int = 20) -> dict[str, dict]:
    """Récupère les infos pour tous les POIs.

    Stratégie :
    1. my_business_info (batch async) — pour les lieux avec fiche Google Business
    2. serp/google/maps/live (fallback) — pour les lieux sans fiche (plages, sites naturels...)
    """
    results = {}
    tag_to_poi = {p["tag"]: p for p in pois}

    # --- Étape 1 : my_business_info (batch async) ---
    log.info("BATCH business_info — keyword principal")
    tag_to_task = {}

    for i in range(0, len(pois), BATCH_SIZE):
        batch = pois[i:i + BATCH_SIZE]
        payload = [{
            "keyword": f"{p['name']} {p['commune']}",
            "location_name": "France",
            "language_code": "fr",
            "tag": p["tag"],
        } for p in batch]
        log.info(f"  POST batch {i // BATCH_SIZE + 1} ({len(batch)} POIs)")
        result = _post("/business_data/google/my_business_info/task_post", payload)
        for task in (result.get("tasks") or []):
            tag = task.get("data", {}).get("tag")
            task_id = task.get("id")
            if tag and task_id:
                tag_to_task[tag] = task_id

    log.info(f"  Attente {wait}s...")
    time.sleep(wait)

    for tag, task_id in tag_to_task.items():
        try:
            data = _fetch_single_business(task_id)
            if data:
                results[tag] = data
                log.info(f"  [{tag}] ✓ business_info")
            else:
                log.info(f"  [{tag}] ✗ pas de fiche")
        except Exception as e:
            log.error(f"  [{tag}] erreur: {e}")

    # --- Étape 2 : Google Maps Live (fallback pour les manquants) ---
    missing_tags = [p["tag"] for p in pois if p["tag"] not in results]
    if missing_tags:
        log.info(f"\nFALLBACK Maps — {len(missing_tags)} POIs sans fiche Business")
        for tag in missing_tags:
            poi = tag_to_poi[tag]
            keyword = f"{poi['name']} {poi['commune']}"
            log.info(f"  [{tag}] Maps: {keyword}")
            try:
                data = _search_maps_live(keyword)
                if data and _maps_result_matches(poi["name"], data.get("name_google",""), data.get("category_google")):
                    results[tag] = data
                    log.info(f"  [{tag}] ✓ '{data.get('name_google')}' lat={data.get('lat')} rating={data.get('rating')}")
                elif data:
                    log.warning(f"  [{tag}] ✗ résultat Maps ne correspond pas: '{data.get('name_google')}'")
                    # Essayer variante sans commune
                    data = _search_maps_live(poi["name"])
                    if data and _maps_result_matches(poi["name"], data.get("name_google",""), data.get("category_google")):
                        results[tag] = data
                        log.info(f"  [{tag}] ✓ (retry) '{data.get('name_google')}' lat={data.get('lat')}")
                    else:
                        log.warning(f"  [{tag}] ✗ pas de résultat fiable")
                else:
                    log.warning(f"  [{tag}] ✗ pas trouvé sur Maps")
            except Exception as e:
                log.error(f"  [{tag}] erreur Maps: {e}")

    log.info(f"business_info terminé: {len(results)}/{len(pois)} POIs")
    return results


# ─────────────────────────────────────────────
# ÉTAPE 2 — Google Reviews
# ─────────────────────────────────────────────

def post_review_tasks(pois_with_cid: list[dict]) -> dict[str, str]:
    tag_to_task = {}
    for i in range(0, len(pois_with_cid), BATCH_SIZE):
        batch = pois_with_cid[i:i + BATCH_SIZE]
        payload = [{
            "cid": p["cid"],
            "location_name": "France",
            "language_code": "fr",
            "depth": REVIEW_DEPTH,
            "tag": p["tag"],
        } for p in batch]
        log.info(f"POST reviews batch {i // BATCH_SIZE + 1} ({len(batch)} POIs)")
        result = _post("/business_data/google/reviews/task_post", payload)
        for task in (result.get("tasks") or []):
            tag = task.get("data", {}).get("tag")
            task_id = task.get("id")
            if tag and task_id:
                tag_to_task[tag] = task_id
    return tag_to_task


def fetch_review_results(tag_to_task: dict[str, str], wait: int = REVIEW_WAIT_SECONDS) -> dict[str, list]:
    log.info(f"Attente {wait}s pour les tasks reviews...")
    time.sleep(wait)

    results = {}
    for tag, task_id in tag_to_task.items():
        try:
            resp = _get(f"/business_data/google/reviews/task_get/{task_id}")
            reviews = []
            for item in _get_items(resp):
                reviews.append({
                    "text": item.get("review_text"),
                    "rating": (item.get("rating") or {}).get("value"),
                    "date": item.get("timestamp"),
                    "owner_response": item.get("owner_answer"),
                })
            results[tag] = reviews[:REVIEW_DEPTH]
            log.info(f"[{tag}] ✓ {len(results[tag])} avis")
        except Exception as e:
            log.error(f"[{tag}] erreur reviews: {e}")

    return results


# ─────────────────────────────────────────────
# ÉTAPE 3 — Photos (SERP Images)
# ─────────────────────────────────────────────

def post_image_tasks(pois: list[dict]) -> dict[str, str]:
    tag_to_task = {}
    for i in range(0, len(pois), BATCH_SIZE):
        batch = pois[i:i + BATCH_SIZE]
        payload = [{
            "keyword": f"{p['name']} {p['commune']} photo",
            "location_name": "France",
            "language_code": "fr",
            "depth": IMAGE_DEPTH,
            "search_param": "tbs=isz:xl,itp:photo,ic:color",  # photos extra-large couleur uniquement
            "tag": p["tag"],
        } for p in batch]
        log.info(f"POST images batch {i // BATCH_SIZE + 1} ({len(batch)} POIs)")
        result = _post("/serp/google/images/task_post", payload)
        for task in (result.get("tasks") or []):
            tag = task.get("data", {}).get("tag")
            task_id = task.get("id")
            if tag and task_id:
                tag_to_task[tag] = task_id
    return tag_to_task


def fetch_image_results(tag_to_task: dict[str, str], main_images: dict[str, str],
                        wait: int = REVIEW_WAIT_SECONDS) -> dict[str, list]:
    log.info(f"Attente {wait}s pour les tasks images...")
    time.sleep(wait)

    results = {}
    for tag, task_id in tag_to_task.items():
        candidates = []
        if main_images.get(tag):
            candidates.append({"url": main_images[tag], "width": 0, "height": 0, "title": ""})
        try:
            resp = _get(f"/serp/google/images/task_get/advanced/{task_id}")
            for item in _get_items(resp):
                img_url = item.get("source_url") or item.get("image_url")
                w = item.get("width") or 0
                h = item.get("height") or 0
                # Pré-filtre : exclure les images trop petites
                if img_url and img_url not in [c["url"] for c in candidates]:
                    if w == 0 or w >= 600:  # accepter si on ne connaît pas la taille
                        candidates.append({"url": img_url, "width": w, "height": h, "title": item.get("title", "")})
            log.info(f"[{tag}] ✓ {len(candidates)} candidats images")
        except Exception as e:
            log.error(f"[{tag}] erreur images: {e}")
        results[tag] = candidates

    return results


# ─────────────────────────────────────────────
# SERP Organic (utilisé par scraper_missing.py)
# ─────────────────────────────────────────────

def search_organic(keyword: str, depth: int = 5) -> list[dict]:
    """Lance une recherche SERP organic LIVE (synchrone) et retourne les URLs + snippets."""
    payload = [{
        "keyword": keyword,
        "location_name": "France",
        "language_code": "fr",
        "depth": depth,
    }]
    result = _post("/serp/google/organic/live/advanced", payload)
    snippets = []
    for item in _get_items(result):
        if item.get("type") == "organic":
            snippets.append({
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "url": item.get("url", ""),
            })
        if len(snippets) >= depth:
            break
    return snippets
