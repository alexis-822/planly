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
        "superficie_ha": {"label": "superficie en hectares", "type": "int"},
        "sentiers_km_total": {"label": "total de km de sentiers balisés", "type": "int"},
        "nb_parcours": {"label": "nombre de parcours balisés", "type": "int"},
        "picnic_tables": {"label": "nombre de tables de pique-nique", "type": "int"},
        "playground": {"label": "aire de jeux pour enfants", "type": "bool"},
        "wildlife_observable": {"label": "faune observable (oiseaux, animaux...)", "type": "bool"},
        "alltrails_url": {"label": "URL AllTrails du lieu", "type": "url"},
        "komoot_url": {"label": "URL Komoot du lieu", "type": "url"},
        "trails": {"label": "liste des sentiers balisés (rando + VTT)", "type": "trails"},
        "trails_display": {"label": "sélection affichage (3 rando + VTT)", "type": "trails_display"},
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
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"```$", "", text).strip()
        m = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
        if m:
            text = m.group(1)
        return json.loads(text)
    except Exception as e:
        log.error(f"  Claude erreur extraction: {e}")
        return {}


HAIKU_SYSTEM_STRICT = """Tu es un extracteur de données strict et factuel.
Règles absolues :
- Tu n'inventes jamais de données
- Tu ne complètes jamais par déduction ou connaissance générale
- Tu n'extrais QUE ce qui est littéralement présent dans le texte fourni
- Si une information est absente ou ambiguë → retourne null pour ce champ
- Tu retournes uniquement du JSON valide, rien d'autre"""


def _call_haiku(client, prompt: str, max_tokens: int = 1000) -> dict | list | None:
    """Appel Claude Haiku strict, retourne le JSON parsé ou None."""
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL_EXTRACT,
            max_tokens=max_tokens,
            system=HAIKU_SYSTEM_STRICT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Supprimer les blocs ```json ... ```
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"```$", "", text).strip()
        # Extraire uniquement le premier objet ou tableau JSON (ignore tout texte après)
        m = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
        if m:
            text = m.group(1)
        return json.loads(text)
    except Exception as e:
        log.error(f"  Haiku erreur: {e}")
        return None


def _snippets_to_text(snippets: list[dict], max_chars: int = 4000) -> str:
    """Convertit des snippets SERP en bloc texte pour Claude."""
    parts = []
    for s in snippets:
        url = s.get("url", "")
        title = s.get("title", "")
        desc = s.get("description", "") or ""
        parts.append(f"[{title}] ({url})\n{desc}")
    return "\n\n".join(parts)[:max_chars]


def _select_display_trails(trails: list) -> dict:
    """Sélectionne les sentiers à afficher : 3 rando (court/moyen/long) + VTT séparés."""
    rando = [t for t in trails if t.get("type") == "rando"]
    vtt = [t for t in trails if t.get("type") == "vtt"]

    def pick_by_distance(pool, min_km, max_km):
        candidates = [t for t in pool if t.get("distance_km") and min_km <= t["distance_km"] < max_km]
        return candidates[0] if candidates else None

    selected_rando = []
    used = set()

    # Court : < 6 km (familles)
    short = pick_by_distance(rando, 0, 6)
    if short:
        selected_rando.append({**short, "display_category": "famille"})
        used.add(short.get("name"))

    # Moyen : 6–12 km (normal)
    medium = pick_by_distance(rando, 6, 12)
    if medium and medium.get("name") not in used:
        selected_rando.append({**medium, "display_category": "normal"})
        used.add(medium.get("name"))

    # Long : > 12 km (sportif)
    long_ = pick_by_distance(rando, 12, 9999)
    if long_ and long_.get("name") not in used:
        selected_rando.append({**long_, "display_category": "sportif"})
        used.add(long_.get("name"))

    # Compléter jusqu'à 5 si pas assez par catégorie
    for t in rando:
        if len(selected_rando) >= 5:
            break
        if t.get("name") not in used:
            selected_rando.append({**t, "display_category": None})
            used.add(t.get("name"))

    # VTT : même logique court/moyen/long
    selected_vtt = []
    used_vtt = set()
    short_vtt = pick_by_distance(vtt, 0, 10)
    if short_vtt:
        selected_vtt.append({**short_vtt, "display_category": "famille"})
        used_vtt.add(short_vtt.get("name"))
    medium_vtt = pick_by_distance(vtt, 10, 25)
    if medium_vtt and medium_vtt.get("name") not in used_vtt:
        selected_vtt.append({**medium_vtt, "display_category": "normal"})
        used_vtt.add(medium_vtt.get("name"))
    long_vtt = pick_by_distance(vtt, 25, 9999)
    if long_vtt and long_vtt.get("name") not in used_vtt:
        selected_vtt.append({**long_vtt, "display_category": "sportif"})
        used_vtt.add(long_vtt.get("name"))
    for t in vtt:
        if len(selected_vtt) >= 5:
            break
        if t.get("name") not in used_vtt:
            selected_vtt.append({**t, "display_category": None})
            used_vtt.add(t.get("name"))

    # Tri final par distance croissante (null en dernier)
    selected_rando.sort(key=lambda t: t.get("distance_km") or 9999)
    selected_vtt.sort(key=lambda t: t.get("distance_km") or 9999)

    return {"rando": selected_rando, "vtt": selected_vtt}


def process_forets_nature(client, poi: dict, report: list) -> dict:
    """Pipeline Forets & Nature — 5 blocs avec fetch direct AllTrails/Komoot."""
    from bs4 import BeautifulSoup

    poi_name = poi.get("name", "")
    specific = poi.setdefault("specific", {})
    status   = poi.setdefault("specific_status", {})

    def _already(key):
        return status.get(key) in ("auto", "manual") and specific.get(key) is not None

    def _set(key, val, src):
        specific[key] = val
        status[key]   = "auto"
        report.append({"poi": poi_name, "field": key, "value": val, "status": "auto",
                        "sources": src if isinstance(src, list) else [src]})
        log.info(f"  [F&N] OK {key} = {val}")

    def _empty(key):
        if not _already(key):
            status[key] = "empty"
            log.info(f"  [F&N] -- {key} = null")

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    }

    def _fetch_soup(url):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            log.warning(f"  [F&N] fetch failed {url[:60]}: {e}")
            return None

    def _soup_text(soup, max_chars=8000):
        return soup.get_text(separator=" ", strip=True)[:max_chars] if soup else ""

    log.info(f"  [F&N] == {poi_name} ==")

    # -------------------------------------------------------------------------
    # BLOC 1 : superficie_ha + sentiers_km_total
    # Sources : website ONF -> Wikipedia -> SERP snippets
    # -------------------------------------------------------------------------
    if not (_already("superficie_ha") and _already("sentiers_km_total")):
        log.info("  [F&N] B1: superficie + sentiers_km")
        text_b1, src_b1 = "", []

        website = poi.get("website") or ""
        if "onf.fr" in website:
            soup = _fetch_soup(website)
            if soup:
                text_b1 = _soup_text(soup, 5000)
                src_b1  = [website]
                log.info(f"  [F&N] B1 source: ONF {website[:60]}")

        if not text_b1:
            snip_w = search_organic(f"{poi_name} wikipedia superficie hectares", depth=5)
            wiki_url = next((s["url"] for s in snip_w if "wikipedia.org" in s.get("url", "")), None)
            if wiki_url:
                soup = _fetch_soup(wiki_url)
                if soup:
                    text_b1 = _soup_text(soup, 5000)
                    src_b1  = [wiki_url]
                    log.info(f"  [F&N] B1 source: Wikipedia {wiki_url[:60]}")
            if not text_b1:
                text_b1 = _snippets_to_text(snip_w)
                src_b1  = [s.get("url", "") for s in snip_w[:3]]

        if text_b1:
            prompt_b1 = (
                f'Texte source sur "{poi_name}" :\n\n{text_b1}\n\n'
                "Cherche UNIQUEMENT les patterns :\n"
                "- superficie_ha : entier avant \"hectares\" ou \"ha\"\n"
                "- sentiers_km_total : entier avant \"km de sentiers\" ou \"kilometres de sentiers\"\n\n"
                '{"superficie_ha": <int|null>, "sentiers_km_total": <int|null>}'
            )
            r = _call_haiku(client, prompt_b1)
            if r and isinstance(r, dict):
                for key in ("superficie_ha", "sentiers_km_total"):
                    if not _already(key):
                        val = r.get(key)
                        _set(key, val, src_b1) if val is not None else _empty(key)
        else:
            _empty("superficie_ha"); _empty("sentiers_km_total")
    else:
        log.info("  [F&N] B1: skip (deja rempli)")

    # -------------------------------------------------------------------------
    # BLOC 2 : nb_parcours via SERP site:alltrails.com (JS-rendered → pas de fetch)
    # -------------------------------------------------------------------------
    alltrails_url = specific.get("alltrails_url")
    if not _already("nb_parcours"):
        if alltrails_url:
            log.info(f"  [F&N] B2: nb_parcours via SERP AllTrails")
            snip_b2 = search_organic(
                f'site:alltrails.com/fr/randonnee {poi_name}', depth=15)
            nb = len([s for s in snip_b2 if "alltrails.com/fr/randonnee" in s.get("url", "")])
            if nb > 0:
                _set("nb_parcours", nb, alltrails_url or "alltrails-serp")
            else:
                _empty("nb_parcours")
        else:
            _empty("nb_parcours")
    else:
        log.info(f"  [F&N] B2: skip (deja rempli: {specific.get('nb_parcours')})")

    # -------------------------------------------------------------------------
    # BLOC 3 : trails[] via SERP site:alltrails.com + site:komoot.com
    # AllTrails/Komoot sont JS-rendered → BeautifulSoup retourne HTML vide.
    # Chaque résultat SERP = 1 trail avec URL + snippet (distance/durée/difficulté).
    # -------------------------------------------------------------------------
    komoot_url = specific.get("komoot_url")

    def _extract_trails_from_serp(snippets, source_label):
        """Extrait la liste de trails depuis des snippets SERP AllTrails/Komoot."""
        if not snippets:
            return []
        # Chaque snippet est un trail potentiel avec son URL
        trail_entries = []
        for s in snippets:
            url = s.get("url", "")
            title = s.get("title", "")
            desc = s.get("description", "") or s.get("snippet", "")
            trail_entries.append(f"URL: {url}\nTitre: {title}\nDesc: {desc}")
        text = "\n\n---\n\n".join(trail_entries[:15])
        prompt = (
            f'Résultats de recherche pour des sentiers autour de "{poi_name}" ({source_label}) :\n\n'
            f'{text}\n\n'
            "Extrais la liste des sentiers de randonnée et VTT.\n"
            "Differencies : rando (a pied) | vtt (velo tout terrain).\n"
            "NE PAS inclure les itineraires cyclables routiers ou routes.\n\n"
            "Pour chaque sentier :\n"
            '{"name":string,"type":"rando"|"vtt","distance_km":float|null,'
            '"duration_min":int|null,"difficulty":int 1-5|null,"trail_url":string|null}\n'
            "difficulty: 1=tres facile 2=facile 3=modere 4=difficile 5=expert\n"
            "trail_url: URL complète AllTrails/Komoot si presente, sinon null.\n"
            "duration_min: convertis heures en minutes (1h30 → 90).\n"
            "Retourne un tableau JSON. Si aucun sentier -> []"
        )
        result = _call_haiku(client, prompt, max_tokens=2500)
        return result if isinstance(result, list) else []

    trails_existing = specific.get("trails")
    # Force re-scrape si des champs sont null dans les trails existants
    has_incomplete = (
        isinstance(trails_existing, list) and
        any(t.get("distance_km") is None or t.get("duration_min") is None
            for t in trails_existing)
    )
    if _already("trails") and isinstance(trails_existing, list) and len(trails_existing) > 0 and not has_incomplete:
        log.info(f"  [F&N] B3: skip (deja rempli: {len(trails_existing)} sentiers complets)")
        trails = trails_existing
    else:
        if has_incomplete:
            log.info(f"  [F&N] B3: re-scrape (trails incomplets: {len(trails_existing)} existants)")
        else:
            log.info("  [F&N] B3: extraction trails via SERP AllTrails + Komoot")

        raw_trails = []

        # Source 1 : SERP site:alltrails.com — chaque résultat = 1 trail avec URL
        if alltrails_url:
            # Extraire le nom du lieu depuis l'URL pour affiner la recherche
            lieu = poi_name.lower().replace(" ", "-").replace("'", "-")[:30]
            snip_at = search_organic(
                f'site:alltrails.com/fr/randonnee {poi_name}', depth=15)
            # Filtrer : garder uniquement les pages trail (pas les pages parc/index)
            snip_at_trails = [s for s in snip_at
                              if "/fr/randonnee/france/" in s.get("url", "")
                              and "/fr/randonnee/france/" != s.get("url", "").rstrip("/")]
            if snip_at_trails:
                trails_at = _extract_trails_from_serp(snip_at_trails, "AllTrails")
                log.info(f"  [F&N] B3 AllTrails SERP -> {len(trails_at)} sentiers ({len(snip_at_trails)} résultats)")
                raw_trails.extend(trails_at)

        # Source 2 : SERP site:komoot.com — deux requêtes (rando + VTT) pour maximiser
        if komoot_url:
            snip_km_r = search_organic(
                f'site:komoot.com/fr-fr/tour {poi_name} randonnee', depth=10)
            snip_km_v = search_organic(
                f'site:komoot.com/fr-fr/tour {poi_name} VTT', depth=10)
            snip_km = snip_km_r + snip_km_v
            snip_km_trails = [s for s in snip_km
                              if "komoot.com" in s.get("url", "")
                              and ("/tour/" in s.get("url", "") or "/fr-fr/tour" in s.get("url", ""))]
            # Dédupliquer par URL
            seen_km = set()
            snip_km_trails_u = []
            for s in snip_km_trails:
                u = s.get("url", "")
                if u not in seen_km:
                    seen_km.add(u)
                    snip_km_trails_u.append(s)
            if snip_km_trails_u:
                trails_km = _extract_trails_from_serp(snip_km_trails_u, "Komoot")
                log.info(f"  [F&N] B3 Komoot SERP -> {len(trails_km)} sentiers ({len(snip_km_trails_u)} résultats)")
                raw_trails.extend(trails_km)

        # Fallback général si SERP site: ne donne rien
        if not raw_trails:
            log.info("  [F&N] B3 fallback SERP général")
            snip_f = search_organic(
                f"{poi_name} randonnee VTT sentiers parcours alltrails komoot distance", depth=10)
            raw_trails = _extract_trails_from_serp(snip_f, "SERP-fallback")

        # Deduplication par nom + merge des champs
        merged = {}
        for t in raw_trails:
            key = (t.get("name") or "").lower().strip()
            if not key:
                continue
            if key not in merged:
                merged[key] = dict(t)
            else:
                for f in ("distance_km", "duration_min", "difficulty", "trail_url"):
                    if merged[key].get(f) is None and t.get(f) is not None:
                        merged[key][f] = t[f]
        trails = list(merged.values())

        # Valider trail_url : vérifier que le slug AllTrails correspond au nom du trail
        import unicodedata
        def _norm(s):
            return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()
        def _url_matches_trail(name, url):
            if not url or "alltrails.com" not in url:
                return True  # pas de validation pour les autres sites
            slug = _norm(url.rstrip("/").split("/")[-1].replace("-", " "))
            words = [w for w in _norm(name).split() if len(w) > 3]
            # Au moins 1 mot significatif du nom présent dans le slug
            return any(w in slug for w in words)
        for t in trails:
            if t.get("trail_url") and not _url_matches_trail(t.get("name", ""), t["trail_url"]):
                log.warning(f"  [F&N] URL mismatch '{t['name']}' -> {t['trail_url'][:60]} → supprimée")
                t["trail_url"] = None

        # Normaliser difficulty si string → int
        _diff_map = {
            "très facile": 1, "tres facile": 1,
            "facile": 2,
            "modéré": 3, "modere": 3, "moyen": 3, "moyenne": 3, "intermédiaire": 3,
            "difficile": 4,
            "très difficile": 5, "tres difficile": 5, "expert": 5,
        }
        for t in trails:
            d = t.get("difficulty")
            if isinstance(d, str):
                t["difficulty"] = _diff_map.get(d.lower().strip()) or None

        # Completer les champs null — stratégie en 3 passes
        def _snip_best_text(snips, prefer_domain=None):
            """Construit le texte le plus riche depuis les snippets, en priorisant prefer_domain."""
            parts = []
            for s in snips[:8]:
                url = s.get("url", "")
                title = s.get("title", "")
                desc = s.get("description", "") or s.get("snippet", "")
                if prefer_domain and prefer_domain in url:
                    parts.insert(0, f"URL: {url}\nTitre: {title}\nDesc: {desc}")
                else:
                    parts.append(f"URL: {url}\nTitre: {title}\nDesc: {desc}")
            return "\n\n".join(parts[:6])

        def _haiku_extract_trail_fields(txt, trail_name, missing_f):
            if not txt or not missing_f:
                return {}
            fields_str = ", ".join(f'"{f}": <valeur|null>' for f in missing_f)
            r = _call_haiku(client,
                f'Données pour le sentier "{trail_name}" :\n{txt}\n\n'
                f'Extrais UNIQUEMENT les champs suivants (NE PAS inventer) : {{{fields_str}}}\n'
                'distance_km: float km (ex: 6.6)\n'
                'duration_min: int minutes (convertis "1h15"→75, "2h"→120, "45min"→45)\n'
                'difficulty: int 1-5 (très facile=1, facile=2, modéré=3, difficile=4, expert=5)\n'
                'Si une valeur est absente du texte → null (ne pas deviner)')
            return r if isinstance(r, dict) else {}

        for t in trails:
            missing_f = [f for f in ("distance_km", "duration_min", "difficulty") if t.get(f) is None]
            if not missing_f:
                continue
            trail_name = t.get("name", "")
            trail_url  = t.get("trail_url", "")

            # Passe 1 : chercher par slug URL si on a l'URL AllTrails
            # Google retourne le snippet exact de cette page (ex: "13,2 km · 2h30 · Modéré")
            if trail_url and "alltrails.com" in trail_url:
                slug = trail_url.rstrip("/").split("/")[-1]
                snip1 = search_organic(f'alltrails {slug}', depth=5)
                txt1  = _snip_best_text(snip1, prefer_domain="alltrails.com")
                if txt1:
                    r1 = _haiku_extract_trail_fields(txt1, trail_name, missing_f)
                    for f in missing_f[:]:
                        if r1.get(f) is not None:
                            t[f] = r1[f]
                            missing_f.remove(f)

            if not missing_f:
                continue

            # Passe 2 : chercher nom + commune sur AllTrails + Visorando + Wikiloc
            commune = poi.get("commune", "") or poi.get("municipality", "") or ""
            # Multi-source : AllTrails, Visorando, Wikiloc, Rando-Vendée
            snip2 = search_organic(
                f'"{trail_name}" {commune} randonnee distance km duree '
                f'(site:alltrails.com OR site:visorando.com OR site:wikiloc.com OR site:rando-vendee.com)',
                depth=8)
            if not snip2:
                snip2 = search_organic(
                    f'"{trail_name}" {commune} randonnee distance duree difficulte', depth=6)
            txt2 = _snip_best_text(snip2, prefer_domain="alltrails.com")
            if txt2:
                r2 = _haiku_extract_trail_fields(txt2, trail_name, missing_f)
                for f in missing_f[:]:
                    if r2.get(f) is not None:
                        t[f] = r2[f]
                        missing_f.remove(f)

            # Trouver URL AllTrails si encore manquante
            if not t.get("trail_url"):
                for s in snip2:
                    u = s.get("url", "")
                    if "alltrails.com/fr/randonnee" in u:
                        t["trail_url"] = u
                        break

        # Exclure les trails fantômes (0 métadonnée utile et nom trop générique)
        trails = [
            t for t in trails
            if t.get("distance_km") is not None
            or t.get("duration_min") is not None
            or t.get("trail_url")
        ]
        specific["trails"] = trails
        status["trails"] = "auto" if trails else "empty"
        nb_r = sum(1 for t in trails if t.get("type") == "rando")
        nb_v = sum(1 for t in trails if t.get("type") in ("vtt", "velo"))
        report.append({"poi": poi_name, "field": "trails", "value": len(trails),
                        "status": status["trails"],
                        "sources": [alltrails_url or "", komoot_url or ""]})
        log.info(f"  [F&N] B3 OK trails = {len(trails)} ({nb_r} rando, {nb_v} VTT)")

    # nb_parcours depuis trails si encore vide
    if not _already("nb_parcours") and trails:
        _set("nb_parcours", len(trails), "trails_count")

    # Selection display
    display = _select_display_trails(trails)
    specific["trails_display"] = display
    status["trails_display"] = "auto" if (display["rando"] or display["vtt"]) else "empty"
    log.info(f"  [F&N] display = {len(display['rando'])} rando + {len(display['vtt'])} VTT")

    # -------------------------------------------------------------------------
    # BLOC 4 : playground + wildlife_observable
    # -------------------------------------------------------------------------
    keys_b4 = [k for k in ("playground", "wildlife_observable") if not _already(k)]
    if keys_b4:
        log.info("  [F&N] B4: playground + wildlife_observable")
        snip4 = search_organic(f"{poi_name} aire de jeux enfants faune animaux", depth=5)
        text4 = _snippets_to_text(snip4, 4000)
        if text4:
            prompt_b4 = (
                f'Texte source sur "{poi_name}" :\n\n{text4}\n\n'
                "playground = true si 'aire de jeux', 'jeux pour enfants', 'playground' mentionne.\n"
                "wildlife_observable = true si faune mentionnee (chevreuil, sanglier, oiseau, renard, cerf, lapin, rapace).\n"
                "Retourne UNIQUEMENT true, false ou null.\n"
                '{"playground": <true|false|null>, "wildlife_observable": <true|false|null>}'
            )
            r = _call_haiku(client, prompt_b4)
            if r and isinstance(r, dict):
                src4 = [s.get("url", "") for s in snip4[:3]]
                for key in keys_b4:
                    val = r.get(key)
                    _set(key, val, src4) if val is not None else _empty(key)
        else:
            for key in keys_b4:
                _empty(key)
    else:
        log.info("  [F&N] B4: skip (deja rempli)")

    # -------------------------------------------------------------------------
    # BLOC 5 : corriger statut alltrails_url / komoot_url
    # -------------------------------------------------------------------------
    for key in ("alltrails_url", "komoot_url"):
        if specific.get(key) and status.get(key) not in ("auto", "manual"):
            status[key] = "auto"
            log.info(f"  [F&N] B5: statut {key} corrige -> auto")

    return poi



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


def process_poi(client, poi: dict, dry_run: bool = False, report: list = None) -> dict:
    """Traite un POI : remplit champs de base + champs spécifiques manquants."""
    if report is None:
        report = []

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

    # Pipeline spécifique Forêts & Nature
    if poi.get("subcategory") == "Forêts & Nature":
        return process_forets_nature(client, poi, report)

    # 1. Recherche SERP par champ manquant → fetch contenu → Claude par batch
    #    On regroupe les champs pour minimiser les appels SERP+Claude
    all_pages = {}  # url -> page dict (cache pour ne pas refetcher)
    field_pages = {}  # field_key -> list of pages

    for field_key, field_def in missing:
        # Ignorer les champs de type trails/url (gérés par pipeline spécifique)
        if field_def.get("type") in ("trails", "url"):
            continue
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
        if field_def.get("type") in ("trails", "url"):
            continue
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
    report = []
    for i, poi in enumerate(pois):
        missing = get_missing_fields(poi)
        if not missing:
            continue

        pois[i] = process_poi(client, poi, report=report)
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

    # Sauvegarder le rapport de champs extraits
    if report:
        report_path = os.path.join(os.path.dirname(__file__), "missing_fields_report.json")
        # Fusionner avec rapport existant si présent
        existing = []
        if os.path.exists(report_path):
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass
        # Dédupliquer par (poi, field) — garder le plus récent
        merged = {(e["poi"], e["field"]): e for e in existing}
        for entry in report:
            merged[(entry["poi"], entry["field"])] = entry
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(list(merged.values()), f, ensure_ascii=False, indent=2)
        log.info(f"Rapport sauvegardé: {report_path} ({len(merged)} entrées)")

    # Mettre à jour le dashboard
    _update_dashboard(pois)


def _update_dashboard(data):
    dashboard_path = os.path.join(os.path.dirname(__file__), "..", "dashboard.html")
    if not os.path.exists(dashboard_path):
        return
    try:
        import copy
        # Copie pour ne pas modifier output_global en mémoire
        dash_data = copy.deepcopy(data)
        # Préfixer les chemins photos avec planly_scraper/ si besoin
        for p in dash_data:
            photos = p.get("photos") or []
            p["photos"] = [
                ("planly_scraper/" + ph) if ph and ph.startswith("images/") else ph
                for ph in photos
            ]

        with open(dashboard_path, "r", encoding="utf-8") as f:
            html = f.read()
        mini = json.dumps(dash_data, ensure_ascii=False, separators=(",", ":"))
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
