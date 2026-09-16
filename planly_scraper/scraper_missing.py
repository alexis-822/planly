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
import datetime
import unicodedata
import urllib.parse
import urllib.robotparser
from html import unescape

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import anthropic
import requests
import truststore
truststore.inject_into_ssl()  # magasin de certificats Windows : chaînes incomplètes (ex. vendee-tourisme.com)
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

# Parcs & Loisirs : remplis uniquement depuis le site officiel (process_parcs_loisirs)
_PARCS_LOISIRS_FIELDS = {
    "pricing": {"label": "tarifs adulte/enfant, tranches d'âge, billet famille", "type": "official"},
    "age_min": {"label": "âge minimum", "type": "official"},
    "activities": {"label": "activités avec âge/taille minimum", "type": "official"},
    "shows": {"label": "animations à heure fixe", "type": "official"},
    "indoor_outdoor": {"label": "intérieur / extérieur / mixte", "type": "official"},
    "booking": {"label": "réservation obligatoire / conseillée / non", "type": "official"},
    "season": {"label": "période d'ouverture", "type": "official"},
    "hours_text": {"label": "horaires d'ouverture", "type": "official"},
    "amenities": {"label": "snack, espace tout-petits, pique-nique, poussette, règles pratiques", "type": "official"},
}

# Sorties & Détente : bars, casinos, cinémas, piscines & spa (process_sorties)
_SORTIES_FIELDS = {
    "pricing": {"label": "tarifs (entrée, séance, accès journée, formules)", "type": "official"},
    "hours_text": {"label": "horaires d'ouverture", "type": "official"},
    "closing_time": {"label": "heure de fermeture la plus tardive", "type": "official"},
    "age_min": {"label": "âge minimum d'accès", "type": "official"},
    "booking": {"label": "réservation obligatoire / conseillée / non", "type": "official"},
    "know": {"label": "3 points « bon à savoir »", "type": "official"},
    "facilities": {"label": "installations, jeux ou salles", "type": "official"},
    "services": {"label": "terrasse, vue, musique live, restauration, tenue, versions", "type": "official"},
    "social": {"label": "pages Instagram et Facebook du lieu", "type": "official"},
}

# Manger & terroir : restaurants, marchés, dégustations (process_manger)
_MANGER_FIELDS = {
    "pricing": {"label": "formules, menus et prix moyen", "type": "official"},
    "cuisine_type": {"label": "type de cuisine ou de lieu", "type": "official"},
    "hours_text": {"label": "horaires des services", "type": "official"},
    "closing_days": {"label": "jour(s) de fermeture", "type": "official"},
    "market_days": {"label": "jours de marché", "type": "official"},
    "products": {"label": "produits phares", "type": "official"},
    "booking": {"label": "réservation obligatoire / conseillée / non", "type": "official"},
    "booking_url": {"label": "lien de réservation", "type": "official"},
    "services": {"label": "terrasse, vue, menu enfant, végétarien, à emporter, couvert, boutique", "type": "official"},
    "know": {"label": "3 points « bon à savoir »", "type": "official"},
    "social": {"label": "pages Instagram et Facebook du lieu", "type": "official"},
}

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
        "altitude_m": {"label": "altitude en mètres", "type": "int"},
        "orientation": {"label": "orientation de la vue", "type": "enum", "options": ["N", "NE", "E", "SE", "S", "SO", "O", "NO", "360"]},
        "view_description": {"label": "description courte de la vue (ce qu'on voit)", "type": "text"},
        "storm_interest": {"label": "spectaculaire par tempête", "type": "bool"},
        "has_orientation_panel": {"label": "panneaux d'orientation présents", "type": "bool"},
        "nb_steps": {"label": "nombre de marches pour accéder", "type": "int"},
        "ideal_weather": {"label": "météo idéale", "type": "enum", "options": ["beau", "vent", "nuageux", "tempete", "all"]},
    },
    "Balades & Promenades": {
        "distance_km": {"label": "distance en kilomètres", "type": "text"},
        "difficulty": {"label": "difficulté", "type": "enum", "options": ["facile", "modéré", "difficile"]},
        "stroller_ok": {"label": "accessible en poussette", "type": "bool"},
        "bike_allowed": {"label": "vélo autorisé", "type": "bool"},
        "loop": {"label": "parcours en boucle", "type": "bool"},
    },
    "Restaurants": _MANGER_FIELDS,
    "Marchés & Terroir": _MANGER_FIELDS,
    "Dégustations": _MANGER_FIELDS,
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
    "Jeux & Divertissement": _PARCS_LOISIRS_FIELDS,
    "Parcs animaliers": _PARCS_LOISIRS_FIELDS,
    "Aquariums": _PARCS_LOISIRS_FIELDS,
    "Parcs botaniques": _PARCS_LOISIRS_FIELDS,
    "Cinéma": _SORTIES_FIELDS,
    "Bars & Ambiance": _SORTIES_FIELDS,
    "Casino & Jeux": _SORTIES_FIELDS,
    "Piscines & Spa": _SORTIES_FIELDS,
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


def process_points_de_vue(client, poi: dict, report: list) -> dict:
    """Pipeline Points de vue — 2 blocs, coût minimal."""
    import re as _re

    poi_name = poi.get("name", "")
    commune  = poi.get("commune", "") or ""
    specific = poi.setdefault("specific", {})
    status   = poi.setdefault("specific_status", {})

    def _already(key):
        return status.get(key) in ("auto", "manual") and specific.get(key) is not None

    def _set(key, val, src):
        specific[key] = val
        status[key]   = "auto"
        report.append({"poi": poi_name, "field": key, "value": val,
                        "status": "auto", "sources": src if isinstance(src, list) else [src]})
        log.info(f"  [PDV] OK {key} = {val}")

    def _empty(key):
        if not _already(key):
            status[key] = "empty"
            log.info(f"  [PDV] -- {key} = null")

    log.info(f"  [PDV] == {poi_name} ==")

    # Construire le corpus : description + avis (gratuit, déjà scraped)
    desc = poi.get("description") or poi.get("description_long") or ""
    conseil = poi.get("conseil_planly") or ""
    reviews = poi.get("reviews") or []
    avis_txt = " ".join(
        r.get("text", "") for r in reviews if r.get("text")
    )
    corpus = f"Description : {desc}\n\nConseil Planly : {conseil}\n\nAvis visiteurs : {avis_txt}"

    # -----------------------------------------------------------------------
    # storm_interest : détection regex (0 coût)
    # -----------------------------------------------------------------------
    if not _already("storm_interest"):
        storm_kw = _re.compile(
            r"tempête|tempete|vague|gros temps|grosse mer|vent fort|impressionnant|spectaculaire|déchaîné",
            _re.I
        )
        val = bool(storm_kw.search(avis_txt + " " + desc))
        _set("storm_interest", val, "avis+description")

    # -----------------------------------------------------------------------
    # BLOC A : orientation, view_description, has_orientation_panel,
    #          nb_steps, ideal_weather  → 1 seul appel Haiku
    # -----------------------------------------------------------------------
    keys_a = [k for k in ("orientation", "view_description", "has_orientation_panel",
                           "nb_steps", "ideal_weather") if not _already(k)]
    if keys_a:
        log.info(f"  [PDV] BLOC A: {keys_a}")
        prompt_a = (
            f'Texte sur le point de vue "{poi_name}" ({commune}) :\n\n'
            f'{corpus[:6000]}\n\n'
            "Extrais UNIQUEMENT les champs présents dans le texte (null si absent) :\n"
            '- orientation: direction principale de la vue parmi N/NE/E/SE/S/SO/O/NO/360. '
            'Cherche des indices : "vue sur la mer à l\'ouest", "coucher de soleil" → O, '
            '"face à l\'île" → cherche direction, "panoramique" → 360\n'
            '- view_description: 1 phrase courte sur ce qu\'on voit (max 80 chars). '
            'Ex: "Vue sur la baie et l\'île d\'Yeu par temps clair"\n'
            '- has_orientation_panel: true si "table d\'orientation" ou "panneau" ou "borne" mentionné\n'
            '- nb_steps: entier si "marches" ou "escaliers" + nombre mentionné\n'
            '- ideal_weather: parmi beau/vent/nuageux/tempete/all. '
            '"par beau temps" → beau, "tempête/vent" → tempete/vent, "toujours magnifique" → all\n\n'
            '{"orientation":<str|null>,"view_description":<str|null>,'
            '"has_orientation_panel":<bool|null>,"nb_steps":<int|null>,"ideal_weather":<str|null>}'
        )
        r = _call_haiku(client, prompt_a, max_tokens=400)
        if r and isinstance(r, dict):
            src = ["description+avis"]
            for key in keys_a:
                val = r.get(key)
                _set(key, val, src) if val is not None else _empty(key)
        else:
            for key in keys_a:
                _empty(key)
    else:
        log.info("  [PDV] BLOC A: skip (deja rempli)")

    # -----------------------------------------------------------------------
    # BLOC B : altitude_m → Wikipedia fetch → SERP
    # -----------------------------------------------------------------------
    if not _already("altitude_m"):
        log.info("  [PDV] BLOC B: altitude_m")
        text_b, src_b = "", []

        # Essai 1 : Wikipedia
        snip_w = search_organic(f"{poi_name} {commune} wikipedia altitude mètres", depth=5)
        wiki_url = next((s["url"] for s in snip_w if "wikipedia.org" in s.get("url", "")), None)
        if wiki_url:
            try:
                from bs4 import BeautifulSoup
                import requests as _req
                resp = _req.get(wiki_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
                soup = BeautifulSoup(resp.text, "html.parser")
                text_b = soup.get_text(" ", strip=True)[:4000]
                src_b  = [wiki_url]
                log.info(f"  [PDV] B source: Wikipedia {wiki_url[:60]}")
            except Exception as e:
                log.warning(f"  [PDV] B Wikipedia fetch fail: {e}")

        # Essai 2 : snippets SERP si Wikipedia n'a pas répondu
        if not text_b:
            text_b = _snippets_to_text(snip_w, 3000)
            src_b  = [s.get("url", "") for s in snip_w[:3]]

        # Essai 3 : SERP dédié altitude/hauteur
        if not text_b:
            snip_alt = search_organic(f"{poi_name} altitude hauteur mètres IGN", depth=5)
            text_b = _snippets_to_text(snip_alt, 3000)
            src_b  = [s.get("url", "") for s in snip_alt[:3]]

        if text_b:
            r = _call_haiku(client,
                f'Texte sur "{poi_name}" :\n{text_b}\n\n'
                'altitude_m : entier en mètres (cherche "X m d\'altitude", "X mètres", "alt. X").\n'
                'NE PAS inventer si absent → null\n'
                '{"altitude_m": <int|null>}')
            if r and isinstance(r, dict) and r.get("altitude_m") is not None:
                _set("altitude_m", r["altitude_m"], src_b)
            else:
                _empty("altitude_m")
        else:
            _empty("altitude_m")
    else:
        log.info(f"  [PDV] BLOC B: skip (deja rempli: {specific.get('altitude_m')})")

    return poi


# ─────────────────────────────────────────────
# Parcs & Loisirs — site officiel uniquement
# ─────────────────────────────────────────────

PARCS_LOISIRS = {"Jeux & Divertissement", "Parcs animaliers", "Aquariums", "Parcs botaniques"}
OFFICIAL_UA = "PlanlyBot/1.0 (guide touristique Vendee)"
NOT_OFFICIAL_DOMAINS = ("facebook.", "instagram.", "tripadvisor.", "google.", "linktr.ee", "pagesjaunes.")
LINK_SCORES = ((r"tarif|prix|billet|ticket", 10), (r"horaire|calendrier|ouverture|pratique|infos", 8),
               (r"jeux?/|machine|roulette|poker|black.?jack|bingo|slot", 7),
               (r"carte|menu|formule|midi", 7),
               (r"activit|attraction|animation|programme|planning|decouvr", 5), (r"reserv", 3))
# recherche Google ciblée, en plus des tarifs et horaires, selon la typologie
SITE_QUERIES = {
    "Casino & Jeux": "jeux machines à sous tables",
    "Restaurants": "carte menu formule midi",
    "Piscines & Spa": "tarifs accès journée soins",
    "Cinéma": "tarifs places",
}
LINK_PENALTY = re.compile(r"anniversaire|groupe|entreprise|seminaire|celibataire|evjf|evg|scolaire|ecole|comite|cse|"
                          r"mariage|recrut|emploi|mentions|cgv|cgu|politique|cookie|actualit|blog|presse", re.I)
INSTITUTIONAL_RE = re.compile(r"(^|[.-])(tourisme|mairie|ville|agglo|communaute)[.-]|\.gouv\.fr$|(^|\.)vendee\.fr$", re.I)

PARCS_PROMPT = """Voici des pages web ({source}) sur "{name}" ({subcategory}, {commune}).
{pages}

---

Extrais UNIQUEMENT ce qui est écrit dans ces pages. Réponds avec ce JSON :
{{
  "pricing": {{
    "free_entry": true seulement si l'entrée est explicitement gratuite ou en accès libre, sinon null,
    "adult": prix adulte en euros (nombre) ou null,
    "child": prix enfant en euros (nombre) ou null,
    "child_age_min": âge minimum du tarif enfant (entier) ou null,
    "child_age_max": âge maximum du tarif enfant (entier) ou null,
    "free_under_age": gratuit en dessous de cet âge (entier) ou null,
    "family_ticket": {{"price": nombre, "adults": entier, "children": entier}} ou null,
    "from_price": prix "à partir de" par personne en euros quand il n'y a pas de tarif adulte/enfant (nombre) ou null,
    "options": [{{"label": texte court (ex: "Forfait 100 billes · 1h"), "price": nombre}}] (forfaits ou formules, 5 maximum, [] si aucun),
    "notes": précision courte (suppléments, saison...) ou null,
    "source_url": URL de la page où figurent les tarifs, ou null,
    "valid_period": année ou saison de validité des tarifs si écrite (ex: "2026", "saison 2026") ou null,
    "evidence": phrase recopiée mot pour mot de la page contenant les prix, ou null
  }},
  "age_min": âge minimum pour venir (entier) ou null,
  "activities": [{{"name": texte, "age_min": entier ou null, "age_max": entier ou null, "height_min_cm": entier ou null, "duration_min": entier ou null, "extra_price": nombre ou null}}],
  "shows": [{{"name": texte, "time": "HH:MM"}}],
  "indoor_outdoor": "intérieur" ou "extérieur" ou "mixte" ou null,
  "booking": "obligatoire" ou "conseillée" ou "non" ou null,
  "season": période d'ouverture en texte court ou null,
  "hours_text": horaires d'ouverture en texte court ou null,
  "amenities": {{"snack": vrai/faux ou null, "kids_zone": espace réservé aux tout-petits vrai/faux ou null, "picnic_area": vrai/faux ou null, "stroller_ok": vrai/faux ou null, "rules": [règles pratiques courtes, ex: "chaussettes obligatoires"]}}
}}

- Recopie les prix exactement tels qu'écrits, sans calcul.

- activities : attractions permanentes accessibles à un visiteur individuel, 8 maximum, [] si aucune.
  Exclure : anniversaires, groupes/scolaires/CE, événements ponctuels ou fêtes (Pâques, Halloween...), ateliers datés, restauration, boutique, location.
- shows : animations ou nourrissages quotidiens à heure fixe, [] si aucun.
- pricing.notes : inclure les gratuités d'accompagnateurs si mentionnées.
- Si plusieurs tarifs existent (haute/basse saison), prends la haute saison et précise-le dans notes."""


SORTIES = {"Bars & Ambiance", "Casino & Jeux", "Cinéma", "Piscines & Spa"}
MANGER = {"Restaurants", "Marchés & Terroir", "Dégustations"}

MANGER_PROMPT = """Voici des pages web ({source}) sur "{name}" ({subcategory}, {commune}).
{pages}

---

Extrais UNIQUEMENT ce qui est écrit dans ces pages. Réponds avec ce JSON :
{{
  "pricing": {{
    "options": [{{"label": "ex: Formule du midi, Menu dégustation, Dégustation 3 vins", "price": nombre}}] (6 maximum, [] si aucun),
    "avg_price": prix moyen par personne à la carte en euros (nombre) ou null,
    "free_entry": true si l'entrée ou la dégustation est gratuite, sinon null,
    "notes": précision courte (boissons comprises, supplément...) ou null,
    "source_url": URL de la page des tarifs ou de la carte, ou null,
    "valid_period": année ou saison si écrite, ou null,
    "evidence": phrase recopiée mot pour mot contenant un prix, ou null
  }},
  "cuisine_type": type de cuisine ou de lieu en 1 à 3 mots (ex: fruits de mer, crêperie, brasserie, marché couvert, cave viticole) ou null,
  "hours_text": horaires des services en texte court ou null,
  "closing_days": jour(s) de fermeture ou null,
  "market_days": jours de marché ou null,
  "products": [produits phares, 5 maximum, [] si sans objet],
  "booking": "obligatoire" ou "conseillée" ou "non" ou null,
  "booking_url": URL de réservation ou null,
  "services": {{"terrace": vrai/faux ou null, "view": texte court ou null, "kids_menu": vrai/faux ou null, "vegetarian": vrai/faux ou null, "takeaway": vrai/faux ou null, "covered": vrai/faux ou null, "shop": vrai/faux ou null}},
  "know": [3 phrases courtes maximum, ce qu'il faut savoir avant d'y aller]
}}

- Recopie les prix exactement tels qu'écrits, sans calcul.
- Ne recopie jamais la carte des plats : seulement les formules et menus avec leur prix.
- N'invente ni horaire ni jour de fermeture : null si ce n'est pas écrit.
- Marchés : market_days et products sont l'essentiel, covered dit si la halle est couverte.
- Dégustations : options = les formules de dégustation, shop = boutique sur place."""

SORTIES_PROMPT = """Voici des pages web ({source}) sur "{name}" ({subcategory}, {commune}).
{pages}

---

Extrais UNIQUEMENT ce qui est écrit dans ces pages. Réponds avec ce JSON :
{{
  "pricing": {{
    "free_entry": true seulement si l'entrée est explicitement gratuite, sinon null,
    "adult": tarif adulte / plein tarif en euros (nombre) ou null,
    "child": tarif enfant ou réduit en euros (nombre) ou null,
    "child_age_max": âge maximum du tarif enfant (entier) ou null,
    "from_price": prix "à partir de" par personne (nombre) ou null,
    "options": [{{"label": texte court (ex: "Accès journée", "Soin 50 min"), "price": nombre}}] (5 maximum, [] si aucun),
    "notes": précision courte ou null,
    "source_url": URL de la page des tarifs ou null,
    "valid_period": année ou saison des tarifs si écrite ou null,
    "evidence": phrase recopiée mot pour mot contenant les prix, ou null
  }},
  "hours_text": horaires d'ouverture en texte court ou null,
  "closing_time": heure de fermeture la plus tardive (ex: "1h", "23h30") ou null,
  "age_min": âge minimum d'accès (entier) ou null,
  "booking": "obligatoire" ou "conseillée" ou "non" ou null,
  "know": [3 phrases courtes maximum, ce qu'il faut savoir avant d'y aller],
  "facilities": [{{"name": texte court, "detail": texte court ou null}}] (installations d'un spa, jeux d'un casino, équipements d'un cinéma ; 6 maximum, [] si aucun),
  "services": {{"terrace": vrai/faux ou null, "view": texte court ou null, "live_music": vrai/faux ou null, "happy_hour": texte court ou null, "restaurant_on_site": vrai/faux ou null, "dress_code": texte court ou null, "id_required": vrai/faux ou null, "screens": entier ou null, "versions": texte court (ex: "VF et VOST") ou null, "snack": vrai/faux ou null, "pmr": vrai/faux ou null}}
}}

- Recopie les prix exactement tels qu'écrits, sans calcul.
- N'invente jamais d'horaire ni d'âge minimum : null si ce n'est pas écrit.
- Pas d'agenda : ignore les concerts, soirées et séances datés, ils changent trop vite.
- "know" : faits pratiques et durables (accès, ambiance, ce qui est compris, contraintes). Pas de superlatif publicitaire.
- Casino : age_min 18 et id_required si la pièce d'identité est exigée. Dans facilities, donne les chiffres utiles au joueur : nombre de machines à sous, nombre de tables de jeu, jeux électroniques et leur nombre (name = le jeu, detail = le nombre et l'horaire s'ils sont écrits). Spa : age_min souvent 16 ou 18.
- Cinéma : screens = nombre de salles, versions = VF/VOST. Bars : closing_time = heure de fermeture."""


def _html_to_text(page_html: str) -> str:
    page_html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page_html, flags=re.S | re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", page_html))
    return re.sub(r"\s+", " ", text).strip()


def _load_robots(home: str):
    parts = urllib.parse.urlsplit(home)
    try:
        resp = requests.get(f"{parts.scheme}://{parts.netloc}/robots.txt", timeout=8,
                            headers={"User-Agent": OFFICIAL_UA})
    except Exception:
        return None
    if resp.status_code >= 400:
        return None
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(resp.text.splitlines())
    return rp


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.")


def _same_site(url: str, domain: str) -> bool:
    host = _host(url)
    return host == domain or host.endswith("." + domain)


def _score_url(url: str, label: str = "") -> int:
    txt = urllib.parse.unquote(url) + " " + label
    score = sum(pts for pat, pts in LINK_SCORES if re.search(pat, txt, re.I))
    return score - 12 if LINK_PENALTY.search(txt) else score


def _fetch_page(url: str, robots) -> dict | None:
    if robots and not robots.can_fetch(OFFICIAL_UA, url):
        log.info(f"    robots.txt refuse : {url[:80]}")
        return None
    headers = {"User-Agent": OFFICIAL_UA}
    try:
        try:
            r = requests.get(url, headers=headers, timeout=12)
        except requests.exceptions.ChunkedEncodingError:
            # certains serveurs coupent les réponses compressées (ex. axeyon-paintball.ovh)
            r = requests.get(url, headers={**headers, "Accept-Encoding": "identity"}, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"    Fetch échoué {url[:80]}: {str(e)[:80]}")
        return None
    if "html" not in r.headers.get("content-type", "") and "xml" not in r.headers.get("content-type", ""):
        return None
    log.info(f"    Page : {url[:90]}")
    return {"url": url, "html": r.text, "content": _html_to_text(r.text)[:20000]}


def official_candidate_urls(home_page: dict, robots) -> list[str]:
    """Pages du site officiel classées par pertinence (liens de l'accueil + sitemap)."""
    home = home_page["url"]
    domain = _host(home)
    # site de groupe (chaîne de casinos, d'hôtels, page de commune) : le lieu vit sous son propre chemin
    base_path = urllib.parse.urlsplit(home).path.rstrip("/")
    if base_path.count("/") < 2:
        base_path = ""
    scores = {}

    lang_re = re.compile(r"^/(en|de|es|it|nl|pt|zh|ja|cs|el|ru|pl|da|sv)(/|$)", re.I)

    def add(url, label=""):
        url = url.split("#")[0].rstrip("/")
        if lang_re.match(urllib.parse.urlsplit(url).path):  # mêmes pages traduites : inutile de les relire
            return
        if _same_site(url, domain) and url != home.rstrip("/"):
            s = _score_url(url, label)
            if base_path:
                s += 12 if urllib.parse.urlsplit(url).path.startswith(base_path + "/") else -8
            if s > 0:
                scores[url] = max(s, scores.get(url, 0))

    for href, label in re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', home_page["html"], flags=re.S | re.I):
        add(urllib.parse.urljoin(home, href.strip()), _html_to_text(label))

    parts = urllib.parse.urlsplit(home)
    sitemaps = list((robots.site_maps() if robots else None) or [f"{parts.scheme}://{parts.netloc}/sitemap.xml"])
    for _ in range(6):
        if not sitemaps:
            break
        sm = _fetch_page(sitemaps.pop(0), robots)
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm["html"] if sm else ""):
            if loc.endswith(".xml"):
                sitemaps.append(loc)
            else:
                add(loc)
    return sorted(scores, key=lambda u: -scores[u])


AGGREGATORS = ("tripadvisor.", "thefork.", "lafourchette.", "petitfute.", "yelp.", "pagesjaunes.",
               "facebook.", "instagram.", "google.", "linktr.ee", "booking.com", "expedia.", "mapstr.",
               "opentable.", "michelin.", "annuaire-entreprises", "societe.com", "infogreffe.", "youtube.")


SOCIAL_RE = re.compile(r"https?://(?:[a-z-]+\.)?(facebook|instagram)\.com/([^\"'<>\s?#]+)", re.I)
SOCIAL_SKIP = re.compile(r"sharer|/share|/plugins/|/tr\b|dialog|intent|^p/$", re.I)


def _social_links(html: str, seed: str = "") -> dict:
    """Liens Instagram / Facebook du lieu : un simple lien, jamais de contenu copié."""
    out = {}
    for url, net, path in [(m.group(0), m.group(1).lower(), m.group(2)) for m in SOCIAL_RE.finditer(seed + " " + (html or ""))]:
        if net in out or SOCIAL_SKIP.search(url) or len(path) < 2:
            continue
        out[net] = url.rstrip("/")
    return out


def _find_official_site(poi: dict) -> str:
    """Cherche le site officiel quand Google ne le donne pas : un mot du nom doit être dans le domaine."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", unicodedata.normalize("NFKD", poi.get("name", "").lower())
                                  .encode("ascii", "ignore").decode()) if len(t) > 3]
    if not tokens:
        return ""
    for s in search_organic(f"{poi.get('name', '')} {poi.get('commune', '')} site officiel", depth=10):
        host = _host(s["url"])
        if any(a in host for a in AGGREGATORS) or INSTITUTIONAL_RE.search(host):
            continue
        flat = re.sub(r"[^a-z0-9]", "", host)
        if any(t in flat for t in tokens):
            log.info(f"  [site officiel trouvé] {host}")
            return f"https://{host}"
    return ""


def _to_float(value) -> float | None:
    try:
        return float(str(value).replace("€", "").replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _price_in_text(value, text: str) -> bool:
    """Le prix extrait doit figurer tel quel dans les pages, à côté d'un symbole euro."""
    n = _to_float(value)
    if n is None:
        return False
    euros, cents = int(n), round((n - int(n)) * 100)
    if cents:
        variants = {f"{euros},{cents:02d}", f"{euros}.{cents:02d}"}
        if cents % 10 == 0:
            variants |= {f"{euros},{cents // 10}", f"{euros}.{cents // 10}"}
        if f"{euros}€{cents:02d}" in text.replace(" ", ""):
            return True
    else:
        variants = {str(euros), f"{euros},00", f"{euros}.00"}
    t = text.replace(" ", " ")
    return any(re.search(rf"(?<![\d,.]){re.escape(v)}(?![\d])\s?(?:€|euros?\b|eur\b)|€\s?{re.escape(v)}(?![\d,.])", t, re.I)
               for v in variants)


def _stale_year(pricing: dict) -> int | None:
    years = [int(y) for y in re.findall(r"\b20\d\d\b", f"{pricing.get('valid_period') or ''} {pricing.get('evidence') or ''}")]
    return max(years) if years and max(years) < datetime.date.today().year else None


def _is_empty(value) -> bool:
    if isinstance(value, dict):
        return all(_is_empty(v) for v in value.values())
    return value in (None, [], "")


def _run_official_pipeline(client, poi: dict, report: list, keys: list, prompt: str,
                           is_complete, label_log: str, source_tag: str) -> dict:
    """Itère site officiel → recherche Google sur le domaine officiel → office de tourisme / commune,
    jusqu'à obtenir des tarifs vérifiés (chiffres présents dans la page source) et des horaires."""
    today = datetime.date.today().isoformat()
    found, tried = {}, set()
    website = (poi.get("website") or "").strip()
    social_seed = website if SOCIAL_RE.search(website) else ""
    if any(d in website for d in NOT_OFFICIAL_DOMAINS):
        website = ""
    if not website:
        website = _find_official_site(poi)
    home = (website if website.startswith("http") else f"https://{website}") if website else ""
    domain = _host(home) if home else ""
    robots = _load_robots(home) if home else None
    site_label = "office de tourisme" if INSTITUTIONAL_RE.search(domain) else "site officiel"

    def complete():
        return is_complete(found, poi)

    def extract(label, pages):
        pages = [p for p in pages if p and p["content"] and p["url"] not in tried]
        tried.update(p["url"] for p in pages)
        if not pages:
            return
        log.info(f"  [{label_log}] {label} : extraction sur {len(pages)} page(s)")
        text = "".join(f"\n\n--- {p['url']} ---\n{p['content']}" for p in pages)
        data = _call_haiku(client, prompt.format(
            source=label, name=poi.get("name", ""), subcategory=poi.get("subcategory", ""),
            commune=poi.get("commune", ""), pages=text), max_tokens=2500)
        if not isinstance(data, dict):
            return
        pr = data.get("pricing") if isinstance(data.get("pricing"), dict) else None
        # Dans un bar ou un restaurant, l'entrée libre ne rend pas la sortie gratuite
        if pr and pr.get("free_entry") and poi.get("subcategory") in ("Bars & Ambiance", "Restaurants"):
            pr.update({"free_entry": None, "adult": None, "child": None})
        if pr and pr.get("free_entry") is True:
            if re.search(r"gratuit|acc[eè]s libre|entr[ée]e libre", text, re.I):
                pr.update({"adult": 0, "child": 0, "family_ticket": None})
            else:
                pr["free_entry"] = None
        if pr and not pr.get("free_entry"):
            for f in ("adult", "child"):
                if pr.get(f) is not None and not _price_in_text(pr[f], text):
                    log.info(f"    ✗ prix {f}={pr[f]} absent des pages → rejeté")
                    pr[f] = None
            ft = pr.get("family_ticket")
            if isinstance(ft, dict) and not _price_in_text(ft.get("price"), text):
                pr["family_ticket"] = None
            for f in ("from_price", "avg_price"):
                if pr.get(f) is not None and not _price_in_text(pr[f], text):
                    pr[f] = None
            pr["options"] = [o for o in (pr.get("options") or [])
                             if isinstance(o, dict) and _price_in_text(o.get("price"), text)][:5]
        if pr and pr.get("adult") is None and pr.get("child") is None and not pr.get("family_ticket") \
                and pr.get("from_price") is None and pr.get("avg_price") is None and not pr.get("options"):
            pr = None
        if pr:
            stale = _stale_year(pr)
            pr.update({"stale": bool(stale), "source_label": label, "verified_at": today})
            if stale:
                log.info(f"    ~ tarifs datés de {stale}, recherche de plus récents")
            old = found.get("pricing")
            if not old or (old.get("stale") and not stale):
                found["pricing"] = pr
        for k in keys:
            if k != "pricing" and k not in found and not _is_empty(data.get(k)):
                found[k] = data[k]

    # 1. Site officiel : accueil + pages les plus pertinentes (liens et sitemap)
    if home:
        home_page = _fetch_page(home, robots)
        if home_page:
            social = _social_links(home_page["html"], social_seed)
            if social:
                found["social"] = social
                log.info(f"    réseaux : {', '.join(social)}")
            pages = [home_page]
            for url in official_candidate_urls(home_page, robots)[:8]:
                time.sleep(1)
                pages.append(_fetch_page(url, robots))
            extract(site_label, pages)

    # 2. Recherche Google limitée au domaine officiel — toujours lancée quand la typologie
    #    a une requête ciblée (pages de jeux, carte d'un restaurant…), même si l'essentiel est déjà trouvé
    if home and (not complete() or SITE_QUERIES.get(poi.get("subcategory"))):
        urls = []
        queries = ["tarifs prix", "horaires ouverture"]
        if SITE_QUERIES.get(poi.get("subcategory")):
            queries.append(SITE_QUERIES[poi["subcategory"]])
        for q in queries:
            for s in search_organic(f"site:{domain} {q}", depth=10):
                if _same_site(s["url"], domain) and s["url"] not in tried and s["url"] not in urls:
                    urls.append(s["url"])
        extract(site_label, [_fetch_page(u, robots) for u in urls[:6]])

    # 3. Pages institutionnelles (office de tourisme, commune)
    if not complete():
        query = f"\"{poi.get('name', '')}\" {poi.get('commune', '')} tarifs horaires"
        commune_slug = re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", poi.get("commune", "").lower()))
        urls = [s["url"] for s in search_organic(query, depth=10)
                if (INSTITUTIONAL_RE.search(_host(s["url"])) or (commune_slug and commune_slug in re.sub(r"[^a-z]", "", _host(s["url"]))))
                and s["url"] not in tried]
        extract("office de tourisme", [_fetch_page(u, _load_robots(u)) for u in urls[:4]])

    for k in keys:
        if _is_empty(found.get(k)):
            poi["specific_status"][k] = "empty"
            log.info(f"    ✗ {k} = null")
            continue
        poi["specific"][k] = found[k]
        poi["specific_status"][k] = "auto"
        report.append({"poi": poi.get("id"), "field": k, "value": found[k], "source": source_tag})
        log.info(f"    ✓ {k} = {str(found[k])[:90]}")

    poi["specific"]["official_source"] = {"url": home or None, "verified_at": today}
    pricing = found.get("pricing") or {}
    for f, target in (("adult", "price_adult"), ("child", "price_child")):
        if pricing.get(f) is not None:
            poi[target] = _to_float(pricing[f])
    if found.get("age_min") is not None:
        poi["age_min"] = found["age_min"]
    return poi


def process_parcs_loisirs(client, poi: dict, report: list) -> dict:
    def is_complete(found, poi):
        pr = found.get("pricing")
        return bool(pr and not pr.get("stale") and (found.get("hours_text") or poi.get("opening_hours")))

    return _run_official_pipeline(client, poi, report, list(_PARCS_LOISIRS_FIELDS), PARCS_PROMPT,
                                  is_complete, "P&L", "parcs_loisirs")


def process_manger(client, poi: dict, report: list) -> dict:
    def is_complete(found, poi):
        pr = found.get("pricing") or {}
        prix = pr.get("options") or pr.get("avg_price") is not None or pr.get("free_entry")
        return bool((found.get("hours_text") or found.get("market_days") or poi.get("opening_hours")) and prix)

    return _run_official_pipeline(client, poi, report, list(_MANGER_FIELDS), MANGER_PROMPT,
                                  is_complete, "M&T", "manger_terroir")


def process_sorties(client, poi: dict, report: list) -> dict:
    def is_complete(found, poi):
        hours = found.get("hours_text") or poi.get("opening_hours")
        return bool(hours and (found.get("pricing") or found.get("know")))

    return _run_official_pipeline(client, poi, report, list(_SORTIES_FIELDS), SORTIES_PROMPT,
                                  is_complete, "S&D", "sorties_detente")


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

    # Familles lues sur le site officiel uniquement (pas de pages tierces)
    if poi.get("subcategory") in PARCS_LOISIRS or poi.get("subcategory") in SORTIES or poi.get("subcategory") in MANGER:
        if not missing:
            return poi
        poi.setdefault("specific", {})
        poi.setdefault("specific_status", {})
        if poi["subcategory"] in SORTIES:
            return process_sorties(client, poi, report)
        if poi["subcategory"] in MANGER:
            return process_manger(client, poi, report)
        return process_parcs_loisirs(client, poi, report)

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

    # Pipeline spécifique Points de vue
    if poi.get("subcategory") == "Points de vue":
        return process_points_de_vue(client, poi, report)

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
    parser.add_argument("--subcategory", action="append", help="Sous-catégorie à traiter (répétable)")
    parser.add_argument("--poi", help="Tags des POIs à traiter, séparés par des virgules")
    args = parser.parse_args()
    if not (args.subcategory or args.poi):
        parser.error("préciser --subcategory ou --poi : les POIs existants ne doivent pas être retraités par défaut")
    target_subcats = set(args.subcategory or [])
    target_ids = {x.strip() for x in args.poi.split(",")} if args.poi else set()

    def selected(p):
        return (not target_subcats or p.get("subcategory") in target_subcats) and \
               (not target_ids or p.get("id") in target_ids)

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
        if not selected(poi):
            continue
        mb = get_missing_base_fields(poi)
        ms = get_missing_fields(poi)
        if mb or ms:
            pois_with_missing += 1
            total_base_missing += len(mb)
            total_missing += len(ms)

    log.info(f"{pois_with_missing} POIs avec champs manquants ({total_base_missing} base + {total_missing} specific)")

    if args.dry_run:
        for poi in pois:
            if not selected(poi):
                continue
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
        if not selected(poi) or not missing:
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
