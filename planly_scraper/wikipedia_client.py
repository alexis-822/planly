import logging
import wikipediaapi
from config import WIKIPEDIA_SUMMARY_MAX

log = logging.getLogger(__name__)

wiki = wikipediaapi.Wikipedia(language="fr", user_agent="Planly/1.0 (contact@planly.app)")


def get_wikipedia_description(poi_name: str, commune: str) -> str | None:
    """Cherche une page Wikipedia FR pour le POI.

    Essaie dans l'ordre :
    1. Nom exact
    2. Nom (Commune)

    Returns:
        Résumé tronqué à WIKIPEDIA_SUMMARY_MAX caractères, ou None.
    """
    # Essai 1 : nom exact
    page = wiki.page(poi_name)
    if page.exists():
        log.info(f"[Wikipedia] ✓ {poi_name}")
        return page.summary[:WIKIPEDIA_SUMMARY_MAX]

    # Essai 2 : nom (commune)
    query = f"{poi_name} ({commune})"
    page = wiki.page(query)
    if page.exists():
        log.info(f"[Wikipedia] ✓ {query}")
        return page.summary[:WIKIPEDIA_SUMMARY_MAX]

    log.info(f"[Wikipedia] ✗ Pas de page pour {poi_name}")
    return None


def fetch_all_wikipedia(pois: list[dict]) -> dict[str, str | None]:
    """Récupère les descriptions Wikipedia pour tous les POIs.

    Returns:
        dict tag -> wikipedia_description (ou None)
    """
    results = {}
    for poi in pois:
        try:
            results[poi["tag"]] = get_wikipedia_description(poi["name"], poi["commune"])
        except Exception as e:
            log.error(f"[Wikipedia] erreur {poi['name']}: {e}")
            results[poi["tag"]] = None
    return results
