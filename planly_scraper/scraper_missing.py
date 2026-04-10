"""
Planly — Script 2 : Remplissage des champs spécifiques manquants
Se lance APRÈS scraper_main.py.

Lit output_global.json, identifie les champs spécifiques null.
Pour chaque champ null :
  1. SERP organic "{nom_poi} {commune} {champ_en_français}"
  2. Claude extrait la valeur depuis les snippets
  3. Si confidence high/medium → remplit + _status auto/uncertain
  4. Si null/low → _status empty

Usage:
    python scraper_missing.py
    python scraper_missing.py --dry-run    # affiche les champs manquants sans scraper
    python scraper_missing.py --max-pois 5 # limite le nombre de POIs traités
"""
import argparse
import io
import json
import logging
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import anthropic
import requests
from config import OUTPUT_GLOBAL, ANTHROPIC_API_KEY, CLAUDE_MODEL_EXTRACT
from dataforseo import search_organic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "scraper_missing.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Définition des champs spécifiques par sous-catégorie
# ─────────────────────────────────────────────

SPECIFIC_FIELDS = {
    "Plages & Côte": {
        "beach_type": {"label": "type de plage — utiliser exactement une de ces valeurs : sable_fin (sable fin, doux), sable_normal (sable ordinaire/grossier), galets, sable_galets (mixte sable et galets), rochers, sable_rochers (mixte sable et rochers)", "type": "enum", "options": ["sable_fin", "sable_normal", "galets", "sable_galets", "rochers", "sable_rochers"]},
        "supervised": {"label": "plage surveillée", "type": "bool"},
        "supervised_start": {"label": "date début surveillance baignade", "type": "text"},
        "supervised_end": {"label": "date fin surveillance baignade", "type": "text"},
        "supervised_hours": {"label": "horaires surveillance baignade", "type": "text"},
        "showers": {"label": "douches disponibles sur la plage", "type": "bool"},
        "wave_profile": {"label": "profil des vagues (calme, modéré, sportif, variable)", "type": "enum", "options": ["calme", "modéré", "sportif", "variable"]},
        "naturist": {"label": "plage naturiste", "type": "bool"},
        "beach_bar": {"label": "bar ou restaurant de plage", "type": "bool"},
    },
    "Forêts & Nature": {
        "terrain_type": {"label": "type de terrain", "type": "enum", "options": ["plat", "vallonné", "marécageux", "sablonneux", "mixte"]},
        "difficulty": {"label": "difficulté du parcours", "type": "enum", "options": ["facile", "modéré", "difficile"]},
        "stroller_ok": {"label": "accessible en poussette", "type": "bool"},
        "bike_allowed": {"label": "vélo autorisé", "type": "bool"},
        "shade_level": {"label": "niveau d'ombre", "type": "enum", "options": ["aucune", "partielle", "totale"]},
    },
    "Points de vue": {
        "terrain_type": {"label": "type de terrain", "type": "enum", "options": ["plat", "falaise", "colline", "rocheux"]},
        "difficulty": {"label": "difficulté d'accès", "type": "enum", "options": ["facile", "modéré", "difficile"]},
        "best_time": {"label": "meilleur moment de la journée pour visiter", "type": "enum", "options": ["lever", "journée", "coucher", "nuit"]},
        "panoramic": {"label": "vue panoramique", "type": "bool"},
    },
    "Balades & Promenades": {
        "distance_km": {"label": "distance en kilomètres", "type": "text"},
        "difficulty": {"label": "difficulté", "type": "enum", "options": ["facile", "modéré", "difficile"]},
        "stroller_ok": {"label": "accessible en poussette", "type": "bool"},
        "bike_allowed": {"label": "vélo autorisé", "type": "bool"},
        "loop": {"label": "parcours en boucle", "type": "bool"},
    },
    "Restaurants": {
        "terrace_view": {"label": "terrasse et vue", "type": "enum", "options": ["aucune", "terrasse", "vue_mer", "terrasse_vue_mer"]},
        "best_dish": {"label": "plat signature ou spécialité", "type": "text"},
        "ambiance": {"label": "ambiance du restaurant", "type": "enum", "options": ["familial", "gastronomique", "bistrot", "brasserie", "décontracté", "chic"]},
        "open_sunday": {"label": "ouvert le dimanche", "type": "bool"},
        "reservation_needed": {"label": "réservation conseillée", "type": "bool"},
        "avg_price": {"label": "prix moyen en euros par personne", "type": "text"},
    },
    "Marchés & Terroir": {
        "market_days": {"label": "jours de marché", "type": "text"},
        "covered": {"label": "marché couvert", "type": "bool"},
        "local_products": {"label": "produits locaux phares", "type": "text"},
    },
    "Dégustations": {
        "product_type": {"label": "type de produit", "type": "enum", "options": ["vin", "miel", "conserves", "sel", "bière", "autre"]},
        "tasting_free": {"label": "dégustation gratuite", "type": "bool"},
        "shop": {"label": "boutique sur place", "type": "bool"},
        "guided_visit": {"label": "visite guidée disponible", "type": "bool"},
    },
    "Nautisme": {
        "sport_type": {"label": "type de sport nautique", "type": "enum", "options": ["surf", "paddle", "kayak", "voile", "char_a_voile", "jet_ski", "plongée", "multi"]},
        "lesson_available": {"label": "cours disponibles", "type": "bool"},
        "rental_available": {"label": "location de matériel", "type": "bool"},
        "min_age_activity": {"label": "âge minimum pour l'activité", "type": "text"},
        "level_required": {"label": "niveau requis", "type": "enum", "options": ["débutant", "intermédiaire", "confirmé", "tous"]},
    },
    "Autres sports": {
        "sport_type": {"label": "type de sport", "type": "text"},
        "lesson_available": {"label": "cours disponibles", "type": "bool"},
        "rental_available": {"label": "location de matériel", "type": "bool"},
        "indoor": {"label": "activité en intérieur", "type": "bool"},
    },
    "Villages & Sites": {
        "historical_period": {"label": "période historique", "type": "text"},
        "guided_visit": {"label": "visite guidée disponible", "type": "bool"},
        "free_entry": {"label": "entrée libre et gratuite", "type": "bool"},
    },
    "Châteaux & Monuments": {
        "historical_period": {"label": "période historique", "type": "text"},
        "guided_visit": {"label": "visite guidée disponible", "type": "bool"},
        "entry_price": {"label": "prix d'entrée en euros", "type": "text"},
        "free_entry": {"label": "entrée libre et gratuite", "type": "bool"},
    },
    "Musées & Culture": {
        "theme": {"label": "thème du musée", "type": "text"},
        "guided_visit": {"label": "visite guidée disponible", "type": "bool"},
        "entry_price": {"label": "prix d'entrée en euros", "type": "text"},
        "free_entry": {"label": "entrée libre et gratuite", "type": "bool"},
        "interactive": {"label": "musée interactif ou ludique", "type": "bool"},
    },
    "Jeux & Divertissement": {
        "activity_type": {"label": "type d'activité", "type": "text"},
        "min_age_activity": {"label": "âge minimum", "type": "text"},
        "indoor": {"label": "activité en intérieur", "type": "bool"},
        "entry_price": {"label": "prix en euros", "type": "text"},
        "group_discount": {"label": "tarif groupe disponible", "type": "bool"},
    },
    "Parcs animaliers": {
        "animal_types": {"label": "types d'animaux présents", "type": "text"},
        "feeding_sessions": {"label": "nourrissage public", "type": "bool"},
        "entry_price": {"label": "prix d'entrée en euros", "type": "text"},
        "petting_area": {"label": "mini-ferme ou espace caresses", "type": "bool"},
    },
    "Aquariums": {
        "tank_count": {"label": "nombre de bassins ou aquariums", "type": "text"},
        "touch_pool": {"label": "bassin tactile", "type": "bool"},
        "entry_price": {"label": "prix d'entrée en euros", "type": "text"},
        "shark_tunnel": {"label": "tunnel à requins", "type": "bool"},
    },
    "Parcs botaniques": {
        "garden_type": {"label": "type de jardin", "type": "enum", "options": ["botanique", "tropical", "japonais", "exotique", "mixte"]},
        "guided_visit": {"label": "visite guidée disponible", "type": "bool"},
        "entry_price": {"label": "prix d'entrée en euros", "type": "text"},
        "free_entry": {"label": "entrée libre et gratuite", "type": "bool"},
    },
    "Cinéma": {
        "screens": {"label": "nombre de salles", "type": "text"},
        "imax_3d": {"label": "salle IMAX ou 3D", "type": "bool"},
        "outdoor": {"label": "cinéma en plein air", "type": "bool"},
    },
    "Bars & Ambiance": {
        "ambiance": {"label": "ambiance du bar", "type": "enum", "options": ["lounge", "festif", "guinguette", "cocktails", "pub", "rooftop"]},
        "live_music": {"label": "musique live", "type": "bool"},
        "terrace_view": {"label": "terrasse ou vue", "type": "enum", "options": ["aucune", "terrasse", "vue_mer", "terrasse_vue_mer", "rooftop"]},
        "open_late": {"label": "ouvert tard le soir", "type": "bool"},
    },
    "Casino & Jeux": {
        "slot_machines": {"label": "machines à sous", "type": "bool"},
        "table_games": {"label": "jeux de table", "type": "bool"},
        "shows": {"label": "spectacles", "type": "bool"},
        "restaurant": {"label": "restaurant sur place", "type": "bool"},
        "min_age": {"label": "âge minimum d'entrée", "type": "text"},
    },
    "Piscines & Spa": {
        "pool_type": {"label": "type d'établissement", "type": "enum", "options": ["piscine", "thalasso", "spa", "aqualudique", "mixte"]},
        "outdoor_pool": {"label": "bassin extérieur", "type": "bool"},
        "sauna_hammam": {"label": "sauna ou hammam", "type": "bool"},
        "kids_area": {"label": "espace enfants", "type": "bool"},
        "entry_price": {"label": "prix d'entrée en euros", "type": "text"},
    },
}


def get_missing_fields(poi: dict) -> list[tuple[str, dict]]:
    """Retourne les champs spécifiques manquants pour un POI."""
    subcat = poi.get("subcategory", "")
    fields_def = SPECIFIC_FIELDS.get(subcat, {})
    if not fields_def:
        return []

    specific = poi.get("specific") or {}
    specific_status = poi.get("specific_status") or {}
    missing = []
    for key, field_def in fields_def.items():
        val = specific.get(key)
        status = specific_status.get(key)
        # Skip si déjà rempli manuellement ou avec confiance
        if status == "manual" or status == "auto":
            continue
        if val is None or val == "" or val is False:
            missing.append((key, field_def))
    return missing


def fetch_page_text(url: str, max_chars: int = 5000) -> str | None:
    """Fetche une page web et extrait le texte brut (sans HTML)."""
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Planly/1.0 (POI enrichment bot)",
            "Accept": "text/html",
        })
        resp.raise_for_status()
        html = resp.text

        # Extraction texte basique : supprimer les tags HTML
        import re as _re
        # Supprimer script/style
        html = _re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", "", html, flags=_re.DOTALL | _re.IGNORECASE)
        # Supprimer les tags
        text = _re.sub(r"<[^>]+>", " ", html)
        # Nettoyer les espaces
        text = _re.sub(r"\s+", " ", text).strip()
        # Décoder les entités HTML basiques
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')

        return text[:max_chars] if text else None
    except Exception as e:
        log.warning(f"    Fetch échoué {url}: {e}")
        return None


def fetch_pages_content(snippets: list[dict], max_pages: int = 5) -> list[dict]:
    """Fetche le contenu réel des pages depuis les URLs SERP."""
    enriched = []
    for s in snippets[:max_pages]:
        url = s.get("url", "")
        log.info(f"    Fetch: {url[:80]}")
        content = fetch_page_text(url)
        enriched.append({
            "url": url,
            "title": s.get("title", ""),
            "content": content or s.get("description", ""),  # fallback sur snippet
        })
    return enriched


def extract_fields_with_claude(client, poi_name: str, missing_fields: list[tuple[str, dict]], pages: list[dict]) -> dict:
    """Utilise Claude pour extraire TOUS les champs manquants en une seule requête depuis le contenu des pages."""
    pages_text = ""
    for i, p in enumerate(pages, 1):
        content = (p.get("content") or "")[:3000]
        pages_text += f"\n\n--- Page {i} : {p['url']} ---\n{content}"

    fields_desc = []
    for key, field_def in missing_fields:
        type_hint = ""
        if field_def["type"] == "bool":
            type_hint = "(true/false)"
        elif field_def["type"] == "enum":
            type_hint = f"(une valeur parmi : {', '.join(field_def['options'])})"
        else:
            type_hint = "(texte court)"
        fields_desc.append(f'  "{key}": {type_hint} — {field_def["label"]}')

    fields_list = "\n".join(fields_desc)

    prompt = f"""Voici le contenu scrappé de {len(pages)} pages web sur le lieu "{poi_name}".

{pages_text}

---

À partir de ces contenus, extrais les valeurs des champs suivants :

{fields_list}

Réponds UNIQUEMENT en JSON valide avec ce format :
{{
  "champ1": {{"value": ..., "confidence": "high" ou "medium"}},
  "champ2": {{"value": null, "confidence": null}},
  ...
}}

Règles :
- "high" = l'info est explicitement mentionnée dans une page
- "medium" = l'info est déduite ou partiellement confirmée
- null = l'info n'est pas trouvable dans les pages
- Pour les booléens : true ou false
- Pour les enums : utilise uniquement les valeurs proposées"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL_EXTRACT,
            max_tokens=1000,
            system="Tu extrais des informations factuelles depuis du contenu web scrappé. Réponds uniquement en JSON valide.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        return json.loads(text)
    except Exception as e:
        log.error(f"  Claude erreur extraction: {e}")
        return {}


def get_missing_base_fields(poi: dict) -> list[str]:
    """Retourne les champs de base manquants (lat, lng, address, etc.)."""
    BASE_FIELDS = ["lat", "lng", "address", "phone", "website", "rating", "reviews_count"]
    missing = []
    for key in BASE_FIELDS:
        if poi.get(key) is None or poi.get(key) == "":
            missing.append(key)
    return missing


def fill_base_fields(client, poi: dict) -> dict:
    """Remplit les champs de base manquants (lat, lng, address...) via SERP + scraping."""
    missing_base = get_missing_base_fields(poi)
    if not missing_base:
        return poi

    poi_name = poi.get("name", "")
    commune = poi.get("commune", "")
    log.info(f"  [BASE] {len(missing_base)} champs de base manquants: {missing_base}")

    # Une seule recherche générale
    snippets = search_organic(f"{poi_name} {commune}", depth=3)
    if not snippets:
        log.info(f"  [BASE] 0 résultats SERP")
        return poi

    pages = fetch_pages_content(snippets, max_pages=3)
    pages_with_content = [p for p in pages if p.get("content")]
    if not pages_with_content:
        return poi

    # Construire le prompt pour les champs de base
    pages_text = ""
    for i, p in enumerate(pages_with_content, 1):
        pages_text += f"\n\n--- Page {i} : {p['url']} ---\n{(p.get('content') or '')[:3000]}"

    fields_desc = {
        "lat": "latitude GPS (nombre décimal, ex: 46.4952)",
        "lng": "longitude GPS (nombre décimal, ex: -1.7888)",
        "address": "adresse postale complète",
        "phone": "numéro de téléphone",
        "website": "site web officiel (URL)",
        "rating": "note moyenne Google ou autre (nombre, ex: 4.5)",
        "reviews_count": "nombre total d'avis (nombre entier)",
    }

    fields_to_extract = {k: v for k, v in fields_desc.items() if k in missing_base}
    fields_list = "\n".join(f'  "{k}": {v}' for k, v in fields_to_extract.items())

    prompt = f"""Voici le contenu de pages web sur le lieu "{poi_name}" situé à {commune}.

{pages_text}

---

Extrais ces informations :

{fields_list}

Réponds UNIQUEMENT en JSON valide :
{{
  "lat": {{"value": 46.xxx, "confidence": "high"}},
  "lng": {{"value": -1.xxx, "confidence": "high"}},
  ...
}}

Si une info n'est pas trouvable, mets {{"value": null, "confidence": null}}."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL_EXTRACT,
            max_tokens=500,
            system="Tu extrais des informations factuelles. Réponds uniquement en JSON valide.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        results = json.loads(text)

        for key in missing_base:
            field_result = results.get(key, {})
            if not isinstance(field_result, dict):
                field_result = {"value": field_result, "confidence": "medium"}
            value = field_result.get("value")
            confidence = field_result.get("confidence")
            if value is not None and confidence in ("high", "medium"):
                poi[key] = value
                log.info(f"  [BASE] ✓ {key} = {value}")
            else:
                log.info(f"  [BASE] ✗ {key} = null")

    except Exception as e:
        log.error(f"  [BASE] Claude erreur: {e}")

    return poi


def process_poi(client, poi: dict, dry_run: bool = False) -> dict:
    """Traite un POI : remplit champs de base + champs spécifiques manquants."""
    missing_base = get_missing_base_fields(poi)
    missing = get_missing_fields(poi)

    if not missing and not missing_base:
        return poi

    poi_name = poi.get("name", "")
    commune = poi.get("commune", "")

    log.info(f"[{poi.get('id')}] base:{len(missing_base)} specific:{len(missing)} manquants")

    if dry_run:
        return poi

    # Étape 0 : remplir les champs de base (lat, lng, address...)
    if missing_base:
        poi = fill_base_fields(client, poi)

    if not missing:
        return poi

    if "specific" not in poi:
        poi["specific"] = {}
    if "specific_status" not in poi:
        poi["specific_status"] = {}

    # 1. Recherche SERP par champ manquant → fetch contenu → Claude par batch
    #    On regroupe les champs pour minimiser les appels SERP+Claude
    all_pages = {}  # url -> page dict (cache pour ne pas refetcher)
    field_pages = {}  # field_key -> list of pages

    for field_key, field_def in missing:
        label_fr = field_def["label"]
        search_query = f"{poi_name} {commune} {label_fr}"
        log.info(f"  → SERP: {search_query}")

        snippets = search_organic(search_query, depth=3)
        if not snippets:
            log.info(f"    ✗ 0 résultats")
            field_pages[field_key] = []
            continue

        # Fetch le contenu des pages (avec cache)
        pages_for_field = []
        for s in snippets[:3]:
            url = s["url"]
            if url not in all_pages:
                log.info(f"    Fetch: {url[:80]}")
                content = fetch_page_text(url)
                all_pages[url] = {
                    "url": url,
                    "title": s.get("title", ""),
                    "content": content or s.get("description", ""),
                }
            pages_for_field.append(all_pages[url])

        pages_with_content = [p for p in pages_for_field if p.get("content")]
        field_pages[field_key] = pages_with_content
        log.info(f"    {len(pages_with_content)} pages avec contenu")

    # 2. Regrouper tous les champs + toutes les pages pour un seul appel Claude
    unique_pages = list(all_pages.values())
    unique_pages = [p for p in unique_pages if p.get("content")]

    if not unique_pages:
        log.info(f"    ✗ Aucune page avec contenu")
        for field_key, _ in missing:
            poi["specific_status"][field_key] = "empty"
        return poi

    log.info(f"    → Claude: extraction de {len(missing)} champs depuis {len(unique_pages)} pages")
    results = extract_fields_with_claude(client, poi_name, missing, unique_pages)

    # 4. Remplir les champs
    for field_key, field_def in missing:
        field_result = results.get(field_key, {})
        if not isinstance(field_result, dict):
            field_result = {"value": field_result, "confidence": "medium"}

        value = field_result.get("value")
        confidence = field_result.get("confidence")

        if confidence == "high" and value is not None:
            poi["specific"][field_key] = value
            poi["specific_status"][field_key] = "auto"
            log.info(f"    ✓ {field_key} = {value} (auto)")
        elif confidence == "medium" and value is not None:
            poi["specific"][field_key] = value
            poi["specific_status"][field_key] = "uncertain"
            log.info(f"    ~ {field_key} = {value} (uncertain)")
        else:
            poi["specific_status"][field_key] = "empty"
            log.info(f"    ✗ {field_key} = null")

    return poi


def main():
    parser = argparse.ArgumentParser(description="Planly — Remplissage champs manquants")
    parser.add_argument("--dry-run", action="store_true", help="Affiche les champs manquants sans scraper")
    parser.add_argument("--max-pois", type=int, default=0, help="Limite le nombre de POIs traités (0 = tous)")
    parser.add_argument("--input", default=OUTPUT_GLOBAL, help="Fichier JSON source")
    args = parser.parse_args()

    # Charger le JSON
    input_path = args.input
    if not os.path.exists(input_path):
        log.error(f"Fichier non trouvé: {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        pois = json.load(f)
    log.info(f"{len(pois)} POIs chargés depuis {input_path}")

    # Compter les champs manquants
    total_missing = 0
    total_base_missing = 0
    pois_with_missing = 0
    for poi in pois:
        mb = get_missing_base_fields(poi)
        ms = get_missing_fields(poi)
        if mb or ms:
            pois_with_missing += 1
            total_base_missing += len(mb)
            total_missing += len(ms)

    log.info(f"{pois_with_missing} POIs avec champs manquants ({total_base_missing} base + {total_missing} specific)")

    if args.dry_run:
        for poi in pois:
            mb = get_missing_base_fields(poi)
            ms = get_missing_fields(poi)
            if mb or ms:
                print(f"  [{poi['id']}] base:{mb} specific:{[k for k, _ in ms]}")
        return

    # Initialiser Claude
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Traiter les POIs
    processed = 0
    for i, poi in enumerate(pois):
        missing = get_missing_fields(poi)
        if not missing:
            continue

        pois[i] = process_poi(client, poi)
        processed += 1

        if args.max_pois and processed >= args.max_pois:
            log.info(f"Limite de {args.max_pois} POIs atteinte")
            break

    # Sauvegarder
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)
    log.info(f"JSON mis à jour: {input_path}")

    # Résumé
    auto = sum(1 for p in pois for s in (p.get("specific_status") or {}).values() if s == "auto")
    uncertain = sum(1 for p in pois for s in (p.get("specific_status") or {}).values() if s == "uncertain")
    empty = sum(1 for p in pois for s in (p.get("specific_status") or {}).values() if s == "empty")
    log.info("=" * 60)
    log.info(f"TERMINÉ — {processed} POIs traités")
    log.info(f"  ✓ auto:      {auto}")
    log.info(f"  ~ uncertain: {uncertain}")
    log.info(f"  ✗ empty:     {empty}")
    log.info("=" * 60)

    # Mettre à jour le dashboard
    _update_dashboard(pois)


def _update_dashboard(data):
    dashboard_path = os.path.join(os.path.dirname(__file__), "..", "dashboard.html")
    if not os.path.exists(dashboard_path):
        return
    try:
        with open(dashboard_path, "r", encoding="utf-8") as f:
            html = f.read()
        mini = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
        marker = "const EMBEDDED_DATA = "
        start = html.index(marker) + len(marker)
        end = html.index("];", start) + 1
        html = html[:start] + mini + html[end:]
        with open(dashboard_path, "w", encoding="utf-8") as f:
            f.write(html)
        log.info(f"Dashboard mis à jour")
    except Exception as e:
        log.warning(f"Dashboard update failed: {e}")


if __name__ == "__main__":
    main()
