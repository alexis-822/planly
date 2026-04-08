import json
import logging
import time
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL_CREATIVE, CLAUDE_BATCH_SIZE

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es un expert du tourisme vendéen et des Pays de la Loire.
Tu enrichis les fiches POI de l'application Planly.
Réponds UNIQUEMENT en JSON valide, sans texte avant ou après."""

USER_PROMPT_TEMPLATE = """Voici les données brutes d'un POI :

NOM : {name}
CATÉGORIE : {category} / {subcategory}
DESCRIPTION GOOGLE : {description_raw}
AVIS CLIENTS (extraits) : {reviews_snippets}
MOTS-CLÉS AVIS : {place_topics}
ATTRIBUTS DISPONIBLES : {attributes_available}
WIKIPEDIA : {wikipedia_description}

Génère les champs manquants au format JSON :

{{
  "description_short": "2 lignes max, accrocheur, pour la card swipe",
  "description_long": "Texte complet 80-120 mots pour la page détail",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "audience": ["famille", "couple", "solo", "ados"],
  "age_min": 0,
  "weather_ok": ["sunny", "cloudy", "rainy"],
  "duration_min": 90,
  "notoriety": "incontournable",  // UNIQUEMENT "incontournable" ou "pepite", pas d'autre valeur
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
  "conseil_planly": "Conseil personnalisé 1-2 phrases selon le profil famille/couple/solo"
}}"""


def _format_reviews(reviews: list[dict] | None) -> str:
    if not reviews:
        return "Aucun avis disponible"
    snippets = []
    for r in reviews[:5]:
        text = (r.get("text") or "")[:200]
        rating = r.get("rating", "?")
        snippets.append(f"[{rating}★] {text}")
    return "\n".join(snippets)


def _format_topics(topics: dict | list | None) -> str:
    if not topics:
        return "Aucun"
    if isinstance(topics, dict):
        return ", ".join(f"{k} ({v})" for k, v in topics.items())
    if isinstance(topics, list):
        parts = []
        for t in topics:
            if isinstance(t, dict):
                parts.append(f"{t.get('title', '')} ({t.get('count', '')})")
            else:
                parts.append(str(t))
        return ", ".join(parts)
    return str(topics)


def enrich_poi(client: anthropic.Anthropic, poi_data: dict) -> dict | None:
    """Appelle Claude API pour enrichir un POI.

    Args:
        poi_data: dict contenant name, category, subcategory, description_raw,
                  reviews, place_topics, attributes_available, wikipedia_description

    Returns:
        dict des champs enrichis, ou None en cas d'erreur
    """
    prompt = USER_PROMPT_TEMPLATE.format(
        name=poi_data.get("name", ""),
        category=poi_data.get("category", ""),
        subcategory=poi_data.get("subcategory", ""),
        description_raw=poi_data.get("description_raw") or "Non disponible",
        reviews_snippets=_format_reviews(poi_data.get("reviews")),
        place_topics=_format_topics(poi_data.get("place_topics")),
        attributes_available=poi_data.get("attributes_available") or "Non disponible",
        wikipedia_description=poi_data.get("wikipedia_description") or "Pas de page Wikipedia",
    )

    for attempt in range(2):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL_CREATIVE,
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            # Nettoyer si Claude ajoute des backticks markdown
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            return json.loads(text)
        except json.JSONDecodeError as e:
            log.warning(f"[Claude] JSON invalide pour {poi_data.get('name')}: {e}")
            if attempt == 0:
                log.info("[Claude] Retry...")
                time.sleep(2)
        except Exception as e:
            log.error(f"[Claude] erreur pour {poi_data.get('name')}: {e}")
            if attempt == 0:
                time.sleep(5)

    return None


def enrich_all(pois_data: list[dict]) -> dict[str, dict | None]:
    """Enrichit tous les POIs via Claude API.

    Args:
        pois_data: list de dicts contenant au minimum 'tag' + données POI

    Returns:
        dict tag -> enriched data (ou None)
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    results = {}

    for i in range(0, len(pois_data), CLAUDE_BATCH_SIZE):
        batch = pois_data[i:i + CLAUDE_BATCH_SIZE]
        log.info(f"Claude enrichissement batch {i // CLAUDE_BATCH_SIZE + 1} ({len(batch)} POIs)")
        for poi in batch:
            tag = poi["tag"]
            enriched = enrich_poi(client, poi)
            results[tag] = enriched
            if enriched:
                log.info(f"[{tag}] ✓ enrichi par Claude")
            else:
                log.warning(f"[{tag}] ✗ enrichissement échoué")
        # Pause entre les batches pour respecter le rate limit
        if i + CLAUDE_BATCH_SIZE < len(pois_data):
            log.info("Pause 5s entre batches Claude...")
            time.sleep(5)

    return results
