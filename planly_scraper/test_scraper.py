"""
Test du pipeline complet sur UN SEUL POI : Grande Plage du Remblai.
Usage : python test_scraper.py
"""
import base64
import io
import json
import os
import sys
import time

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ─── Config ───
DATAFORSEO_LOGIN = os.environ.get("DATAFORSEO_LOGIN", "")
DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATAFORSEO_BASE = "https://api.dataforseo.com/v3"

TEST_POI = {
    "tag": "grande_plage_du_remblai",
    "name": "Grande Plage du Remblai",
    "category": "Nature & Grand Air",
    "subcategory": "Plages & Côte",
    "commune": "Les Sables-d'Olonne",
}

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "test_output.json")


def _dfs_headers():
    creds = base64.b64encode(f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}


def step(num, title):
    print(f"\n{'='*60}")
    print(f"  ÉTAPE {num} — {title}")
    print(f"{'='*60}")


# ═══════════════════════════════════════════
# ÉTAPE 1 — DataForSEO my_business_info
# ═══════════════════════════════════════════
def test_business_info():
    step(1, "DataForSEO my_business_info")

    if not DATAFORSEO_LOGIN:
        print("⚠ DATAFORSEO_LOGIN non défini — skip")
        return None

    # Essayer plusieurs variantes de keywords
    keyword_variants = [
        f"{TEST_POI['name']} {TEST_POI['commune']}",
        f"Plage du Remblai Les Sables-d'Olonne",
        f"Le Remblai Les Sables-d'Olonne",
        f"Grande Plage Les Sables-d'Olonne",
    ]

    for keyword in keyword_variants:
        payload = [{
            "keyword": keyword,
            "location_name": "France",
            "language_code": "fr",
            "tag": TEST_POI["tag"],
        }]

        print(f"\nPOST → keyword: {keyword}")
        resp = requests.post(f"{DATAFORSEO_BASE}/business_data/google/my_business_info/task_post",
                             json=payload, headers=_dfs_headers(), timeout=60)
        resp.raise_for_status()
        result = resp.json()

        task_id = None
        for task in result.get("tasks", []):
            task_id = task.get("id")
            print(f"  Task ID: {task_id}")

        if not task_id:
            print("  ❌ Aucun task_id")
            continue

        print(f"  ⏳ Attente 20s...")
        time.sleep(20)

        resp = requests.get(f"{DATAFORSEO_BASE}/business_data/google/my_business_info/task_get/{task_id}",
                            headers=_dfs_headers(), timeout=60)
        resp.raise_for_status()
        result = resp.json()

        items = []
        for task in result.get("tasks", []):
            for r in (task.get("result") or []):
                for item in (r.get("items") or []):
                    items.append(item)

        if items:
            print(f"  ✅ Trouvé avec keyword: {keyword}")
            break
        else:
            print(f"  ✗ Pas de résultat")

    if not items:
        print("❌ Aucun résultat")
        print(json.dumps(result, indent=2, ensure_ascii=False)[:3000])
        return None

    item = items[0]
    print(f"\n✅ Résultat trouvé :")
    print(f"  Nom Google : {item.get('title')}")
    print(f"  Lat/Lng    : {item.get('latitude')}, {item.get('longitude')}")
    print(f"  Adresse    : {item.get('address')}")
    print(f"  Rating     : {(item.get('rating') or {}).get('value')} ({(item.get('rating') or {}).get('votes_count')} avis)")
    print(f"  CID        : {item.get('cid')}")
    print(f"  Place ID   : {item.get('place_id')}")
    print(f"  Main image : {(item.get('main_image') or 'N/A')[:80]}")
    print(f"  Catégorie  : {item.get('category')}")

    # Save raw for debug
    with open(os.path.join(os.path.dirname(__file__), "test_raw_business.json"), "w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False, indent=2)
    print(f"  → JSON brut sauvé dans test_raw_business.json")

    return item


# ═══════════════════════════════════════════
# ÉTAPE 2 — Google Reviews
# ═══════════════════════════════════════════
def test_reviews(cid):
    step(2, "DataForSEO Google Reviews")

    if not cid:
        print("⚠ Pas de CID — skip")
        return []

    payload = [{
        "cid": cid,
        "location_name": "France",
        "language_code": "fr",
        "depth": 5,
        "tag": TEST_POI["tag"],
    }]

    print(f"POST → cid: {cid}")
    resp = requests.post(f"{DATAFORSEO_BASE}/business_data/google/reviews/task_post",
                         json=payload, headers=_dfs_headers(), timeout=60)
    resp.raise_for_status()
    result = resp.json()

    task_id = None
    for task in result.get("tasks", []):
        task_id = task.get("id")
        print(f"Task ID: {task_id}")

    if not task_id:
        print("❌ Aucun task_id")
        return []

    print(f"⏳ Attente 20s...")
    time.sleep(20)

    resp = requests.get(f"{DATAFORSEO_BASE}/business_data/google/reviews/task_get/{task_id}",
                        headers=_dfs_headers(), timeout=60)
    resp.raise_for_status()
    result = resp.json()

    reviews = []
    for task in result.get("tasks", []):
        for r in task.get("result", []):
            for item in r.get("items", []):
                reviews.append({
                    "text": item.get("review_text"),
                    "rating": (item.get("rating") or {}).get("value"),
                    "date": item.get("timestamp"),
                    "owner_response": item.get("owner_answer"),
                })

    print(f"\n✅ {len(reviews)} avis récupérés")
    for i, rev in enumerate(reviews[:5]):
        print(f"  [{rev['rating']}★] {(rev['text'] or '')[:100]}")

    return reviews[:5]


# ═══════════════════════════════════════════
# ÉTAPE 3 — SERP Images
# ═══════════════════════════════════════════
def test_images(main_image):
    step(3, "DataForSEO SERP Google Images")

    if not DATAFORSEO_LOGIN:
        print("⚠ DATAFORSEO_LOGIN non défini — skip")
        return [main_image] if main_image else []

    payload = [{
        "keyword": f"{TEST_POI['name']} {TEST_POI['commune']}",
        "location_name": "France",
        "language_code": "fr",
        "depth": 5,
        "tag": TEST_POI["tag"],
    }]

    print(f"POST → keyword: {payload[0]['keyword']}")
    resp = requests.post(f"{DATAFORSEO_BASE}/serp/google/images/task_post",
                         json=payload, headers=_dfs_headers(), timeout=60)
    resp.raise_for_status()
    result = resp.json()

    task_id = None
    for task in result.get("tasks", []):
        task_id = task.get("id")
        print(f"Task ID: {task_id}")

    if not task_id:
        print("❌ Aucun task_id")
        return [main_image] if main_image else []

    print(f"⏳ Attente 15s...")
    time.sleep(15)

    resp = requests.get(f"{DATAFORSEO_BASE}/serp/google/images/task_get/advanced/{task_id}",
                        headers=_dfs_headers(), timeout=60)
    resp.raise_for_status()
    result = resp.json()

    photos = []
    if main_image:
        photos.append(main_image)

    for task in result.get("tasks", []):
        for r in (task.get("result") or []):
            print(f"\n  DEBUG — items_count: {r.get('items_count')}, item_types: {r.get('item_types')}")
            for item in (r.get("items") or []):
                # Debug : afficher les clés disponibles et le type
                print(f"  DEBUG item type={item.get('type')} keys={list(item.keys())[:10]}")
                # Essayer plusieurs noms de champs possibles
                url = item.get("image_url") or item.get("source_url") or item.get("encoded_url")
                if not url and "images" in item:
                    # Parfois les images sont dans un sous-objet
                    for img in (item.get("images") or []):
                        url = img.get("url") or img.get("image_url")
                        if url:
                            break
                if url and url not in photos and len(photos) < 3:
                    photos.append(url)
                    print(f"  → ajouté: {url[:80]}")

    # Sauver la réponse brute pour debug
    with open(os.path.join(os.path.dirname(__file__), "test_raw_images.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  → Réponse brute sauvée dans test_raw_images.json")

    print(f"\n✅ {len(photos)} photos au total")
    for p in photos:
        print(f"  {p[:100]}")

    return photos


# ═══════════════════════════════════════════
# ÉTAPE 4 — Wikipedia FR
# ═══════════════════════════════════════════
def test_wikipedia():
    step(4, "Wikipedia FR")

    try:
        import wikipediaapi
    except ImportError:
        print("⚠ wikipedia-api non installé — pip install wikipedia-api")
        return None

    wiki = wikipediaapi.Wikipedia(language="fr", user_agent="Planly/1.0 (test)")

    searches = [
        "Grande Plage du Remblai",
        "Plage du Remblai",
        "Remblai (Les Sables-d'Olonne)",
        "Les Sables-d'Olonne",
    ]

    for query in searches:
        print(f"  Essai: '{query}'... ", end="")
        page = wiki.page(query)
        if page.exists():
            desc = page.summary[:500]
            print(f"✅ trouvé ({len(desc)} chars)")
            print(f"  → {desc[:200]}...")
            return desc
        else:
            print("✗")

    print("❌ Aucune page trouvée")
    return None


# ═══════════════════════════════════════════
# ÉTAPE 5 — Claude API enrichissement
# ═══════════════════════════════════════════
def test_claude(business_data, reviews, wikipedia_desc):
    step(5, "Claude API enrichissement")

    if not ANTHROPIC_API_KEY:
        print("⚠ ANTHROPIC_API_KEY non défini — skip")
        return None

    try:
        import anthropic
    except ImportError:
        print("⚠ anthropic non installé — pip install anthropic")
        return None

    # Format reviews
    reviews_text = "Aucun avis"
    if reviews:
        snippets = []
        for r in reviews[:5]:
            snippets.append(f"[{r.get('rating', '?')}★] {(r.get('text') or '')[:200]}")
        reviews_text = "\n".join(snippets)

    # Format topics
    topics = business_data.get("place_topics") if business_data else None
    topics_text = "Aucun"
    if topics:
        if isinstance(topics, dict):
            topics_text = ", ".join(f"{k} ({v})" for k, v in topics.items())
        elif isinstance(topics, list):
            parts = []
            for t in topics:
                if isinstance(t, dict):
                    parts.append(f"{t.get('title', '')} ({t.get('count', '')})")
            topics_text = ", ".join(parts)

    system_prompt = """Tu es un expert du tourisme vendéen et des Pays de la Loire.
Tu enrichis les fiches POI de l'application Planly.
Réponds UNIQUEMENT en JSON valide, sans texte avant ou après."""

    user_prompt = f"""Voici les données brutes d'un POI :

NOM : {TEST_POI['name']}
CATÉGORIE : {TEST_POI['category']} / {TEST_POI['subcategory']}
DESCRIPTION GOOGLE : {(business_data or {}).get('description') or 'Non disponible'}
AVIS CLIENTS (extraits) : {reviews_text}
MOTS-CLÉS AVIS : {topics_text}
ATTRIBUTS DISPONIBLES : {(business_data or {}).get('attributes', {}).get('available_attributes') or 'Non disponible'}
WIKIPEDIA : {wikipedia_desc or 'Pas de page Wikipedia'}

Génère les champs manquants au format JSON :

{{
  "description_short": "2 lignes max, accrocheur, pour la card swipe",
  "description_long": "Texte complet 80-120 mots pour la page détail",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "audience": ["famille", "couple", "solo", "ados"],
  "age_min": 0,
  "weather_ok": ["sunny", "cloudy", "rainy"],
  "duration_min": 90,
  "notoriety": "incontournable",
  "accessibility": {{
    "wheelchair": true,
    "walking_difficulty": true,
    "stroller": true
  }},
  "dogs_allowed": true,
  "is_indoor": false,
  "has_height": false,
  "animals_captive": false,
  "rainy_day_activity": false,
  "conseil_planly": "Conseil personnalisé 1-2 phrases"
}}"""

    print(f"Appel Claude (claude-sonnet-4-6)...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text.strip()

        # Clean markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        enriched = json.loads(text)
        print(f"\n✅ Enrichissement réussi")
        print(f"  description_short : {enriched.get('description_short', '—')}")
        print(f"  tags              : {enriched.get('tags', [])}")
        print(f"  audience          : {enriched.get('audience', [])}")
        print(f"  notoriety         : {enriched.get('notoriety', '—')}")
        print(f"  duration_min      : {enriched.get('duration_min', '—')}")
        print(f"  conseil_planly    : {enriched.get('conseil_planly', '—')[:100]}")
        return enriched

    except json.JSONDecodeError as e:
        print(f"❌ JSON invalide : {e}")
        print(f"  Réponse brute : {text[:500]}")
        return None
    except Exception as e:
        print(f"❌ Erreur Claude : {e}")
        return None


# ═══════════════════════════════════════════
# ÉTAPE 6 — Merge & Save
# ═══════════════════════════════════════════
def test_merge(business_data, reviews, photos, wikipedia_desc, enriched):
    step(6, "Merge & sauvegarde test_output.json")

    from datetime import datetime, timezone
    biz = business_data or {}
    enr = enriched or {}
    rating = biz.get("rating") or {}
    attrs = biz.get("attributes") or {}
    now = datetime.now(timezone.utc).isoformat()

    merged = {
        "id": TEST_POI["tag"],
        "name": biz.get("title") or TEST_POI["name"],
        "category": TEST_POI["category"],
        "subcategory": TEST_POI["subcategory"],
        "commune": TEST_POI["commune"],
        "zone": None,
        "poi_format": "poi",
        "lat": biz.get("latitude"),
        "lng": biz.get("longitude"),
        "address": biz.get("address"),
        "phone": biz.get("phone"),
        "website": biz.get("url"),
        "rating": rating.get("value") if isinstance(rating, dict) else None,
        "reviews_count": rating.get("votes_count") if isinstance(rating, dict) else None,
        "rating_distribution": biz.get("rating_distribution"),
        "opening_hours": (biz.get("work_time") or {}).get("timetable"),
        "popular_times": biz.get("popular_times"),
        "price_level": biz.get("price_level"),
        "photos": photos or [],
        "reviews": reviews or [],
        "place_topics": biz.get("place_topics"),
        "booking_url": biz.get("local_business_links"),
        "cid": biz.get("cid"),
        "place_id": biz.get("place_id"),
        "wikipedia_description": wikipedia_desc,
        "description_short": enr.get("description_short"),
        "description_long": enr.get("description_long"),
        "tags": enr.get("tags"),
        "audience": enr.get("audience"),
        "age_min": enr.get("age_min"),
        "weather_ok": enr.get("weather_ok"),
        "duration_min": enr.get("duration_min"),
        "notoriety": enr.get("notoriety"),
        "accessibility": enr.get("accessibility"),
        "dogs_allowed": enr.get("dogs_allowed"),
        "is_indoor": enr.get("is_indoor"),
        "has_height": enr.get("has_height"),
        "animals_captive": enr.get("animals_captive"),
        "rainy_day_activity": enr.get("rainy_day_activity"),
        "conseil_planly": enr.get("conseil_planly"),
        "specific": {},
        "scraped_at": now if business_data else None,
        "enriched_at": now if enriched else None,
        "status": "complete" if business_data and enriched else "partial" if business_data or enriched else "empty",
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump([merged], f, ensure_ascii=False, indent=2)

    print(f"\n✅ Sauvegardé : {OUTPUT_FILE}")
    print(f"  Status: {merged['status']}")

    # Résumé des champs
    print(f"\n{'─'*40}")
    print(f"  RÉSUMÉ DES CHAMPS")
    print(f"{'─'*40}")
    filled = []
    empty = []
    for key, val in merged.items():
        if key in ("id", "status", "scraped_at", "enriched_at", "specific"):
            continue
        if val is None or val == [] or val == {} or val == "":
            empty.append(key)
        else:
            filled.append(key)

    print(f"\n  ✅ Remplis ({len(filled)}) :")
    for k in filled:
        v = merged[k]
        display = str(v)[:60] if not isinstance(v, (list, dict)) else f"[{len(v)} items]" if isinstance(v, list) else "{...}"
        print(f"     {k}: {display}")

    print(f"\n  ❌ Vides ({len(empty)}) :")
    for k in empty:
        print(f"     {k}")

    return merged


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════
if __name__ == "__main__":
    print("╔══════════════════════════════════════════════╗")
    print("║  PLANLY — Test scraper (1 POI)               ║")
    print("║  Grande Plage du Remblai, Les Sables          ║")
    print("╚══════════════════════════════════════════════╝")

    # Check credentials
    print(f"\nCredentials:")
    print(f"  DATAFORSEO_LOGIN  : {'✅ ' + DATAFORSEO_LOGIN[:4] + '...' if DATAFORSEO_LOGIN else '❌ manquant'}")
    print(f"  DATAFORSEO_PASSWD : {'✅ ****' if DATAFORSEO_PASSWORD else '❌ manquant'}")
    print(f"  ANTHROPIC_API_KEY : {'✅ ' + ANTHROPIC_API_KEY[:8] + '...' if ANTHROPIC_API_KEY else '❌ manquant'}")

    # Run pipeline
    business_data = test_business_info()
    cid = (business_data or {}).get("cid")
    main_image = (business_data or {}).get("main_image")

    reviews = test_reviews(cid)
    photos = test_images(main_image)
    wikipedia_desc = test_wikipedia()
    enriched = test_claude(business_data, reviews, wikipedia_desc)
    merged = test_merge(business_data, reviews, photos, wikipedia_desc, enriched)

    print(f"\n{'='*60}")
    print(f"  PIPELINE TERMINÉ")
    print(f"{'='*60}")
