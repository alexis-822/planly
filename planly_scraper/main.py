"""
Planly POI Scraper — Pipeline complet
Scrape 97 POIs via DataForSEO + Wikipedia + Claude API → JSON Supabase-ready.

Usage:
    python main.py                  # Pipeline complet
    python main.py --skip-dataforseo # Passe DataForSEO, fait Wikipedia + Claude seulement
    python main.py --only-wikipedia  # Wikipedia uniquement
    python main.py --dry-run         # Charge le Excel, affiche les POIs, ne scrape rien
"""
import argparse
import json
import logging
import sys
import os

# Ajouter le dossier courant au path pour les imports
sys.path.insert(0, os.path.dirname(__file__))

from config import OUTPUT_DIR
from poi_loader import load_pois
from dataforseo import (
    post_business_tasks, fetch_business_results,
    post_review_tasks, fetch_review_results,
    post_image_tasks, fetch_image_results,
)
from wikipedia_client import fetch_all_wikipedia
from claude_enricher import enrich_all
from merger import merge_and_save_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "scraper.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def run_dataforseo(pois: list[dict]) -> tuple[dict, dict, dict]:
    """Exécute les 3 étapes DataForSEO : business_info, reviews, images."""

    # ÉTAPE 1 — my_business_info
    log.info("=" * 60)
    log.info("ÉTAPE 1 — DataForSEO my_business_info")
    log.info("=" * 60)
    tag_to_task = post_business_tasks(pois)
    log.info(f"{len(tag_to_task)} tasks envoyées")
    business_results = fetch_business_results(tag_to_task)
    log.info(f"{len(business_results)}/{len(pois)} POIs avec résultats business_info")

    # ÉTAPE 2 — Reviews (uniquement pour les POIs avec cid)
    log.info("=" * 60)
    log.info("ÉTAPE 2 — DataForSEO Google Reviews")
    log.info("=" * 60)
    pois_with_cid = []
    for poi in pois:
        biz = business_results.get(poi["tag"], {})
        if biz.get("cid"):
            pois_with_cid.append({**poi, "cid": biz["cid"]})
    log.info(f"{len(pois_with_cid)} POIs avec cid → envoi reviews")

    review_results = {}
    if pois_with_cid:
        review_tag_to_task = post_review_tasks(pois_with_cid)
        review_results = fetch_review_results(review_tag_to_task)
    log.info(f"{len(review_results)} POIs avec avis récupérés")

    # ÉTAPE 3 — Photos supplémentaires
    log.info("=" * 60)
    log.info("ÉTAPE 3 — DataForSEO SERP Images")
    log.info("=" * 60)
    # On demande des images pour tous les POIs
    image_tag_to_task = post_image_tasks(pois)
    main_images = {
        tag: biz.get("main_image")
        for tag, biz in business_results.items()
        if biz.get("main_image")
    }
    photo_results = fetch_image_results(image_tag_to_task, main_images)
    log.info(f"{len(photo_results)} POIs avec photos")

    return business_results, review_results, photo_results


def run_wikipedia(pois: list[dict]) -> dict:
    """Exécute l'étape Wikipedia."""
    log.info("=" * 60)
    log.info("ÉTAPE 4 — Wikipedia FR")
    log.info("=" * 60)
    wiki_results = fetch_all_wikipedia(pois)
    found = sum(1 for v in wiki_results.values() if v)
    log.info(f"{found}/{len(pois)} POIs avec description Wikipedia")
    return wiki_results


def run_claude_enrichment(pois: list[dict], business_results: dict,
                          review_results: dict, wikipedia_results: dict) -> dict:
    """Exécute l'étape Claude enrichissement."""
    log.info("=" * 60)
    log.info("ÉTAPE 5 — Claude API enrichissement")
    log.info("=" * 60)

    # Préparer les données pour Claude
    pois_for_claude = []
    for poi in pois:
        tag = poi["tag"]
        biz = business_results.get(tag, {})
        pois_for_claude.append({
            "tag": tag,
            "name": poi["name"],
            "category": poi["category"],
            "subcategory": poi["subcategory"],
            "description_raw": biz.get("description_raw"),
            "reviews": review_results.get(tag, []),
            "place_topics": biz.get("place_topics"),
            "attributes_available": biz.get("attributes_available"),
            "wikipedia_description": wikipedia_results.get(tag),
        })

    enriched_results = enrich_all(pois_for_claude)
    success = sum(1 for v in enriched_results.values() if v)
    log.info(f"{success}/{len(pois)} POIs enrichis par Claude")
    return enriched_results


def main():
    parser = argparse.ArgumentParser(description="Planly POI Scraper")
    parser.add_argument("--skip-dataforseo", action="store_true", help="Skip DataForSEO steps")
    parser.add_argument("--only-wikipedia", action="store_true", help="Only run Wikipedia step")
    parser.add_argument("--dry-run", action="store_true", help="Load Excel only, no scraping")
    args = parser.parse_args()

    # Charger les POIs
    log.info("Chargement des POIs depuis Excel...")
    pois = load_pois()
    log.info(f"{len(pois)} POIs chargés")

    if args.dry_run:
        for p in pois:
            print(f"  [{p['tag']}] {p['name']} — {p['category']} / {p['subcategory']} — {p['commune']}")
        log.info("Dry run terminé.")
        return

    # Résultats vides par défaut
    business_results: dict = {}
    review_results: dict = {}
    photo_results: dict = {}
    wikipedia_results: dict = {}
    enriched_results: dict = {}

    # DataForSEO
    if not args.skip_dataforseo and not args.only_wikipedia:
        business_results, review_results, photo_results = run_dataforseo(pois)

    # Wikipedia
    if not args.only_wikipedia or args.only_wikipedia:
        wikipedia_results = run_wikipedia(pois)

    # Claude enrichissement
    if not args.only_wikipedia:
        enriched_results = run_claude_enrichment(
            pois, business_results, review_results, wikipedia_results
        )

    # Fusion + sauvegarde
    log.info("=" * 60)
    log.info("FUSION & SAUVEGARDE")
    log.info("=" * 60)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_merged = merge_and_save_all(
        pois, business_results, review_results, photo_results,
        wikipedia_results, enriched_results,
    )

    # Résumé
    complete = sum(1 for p in all_merged if p["status"] == "complete")
    partial = sum(1 for p in all_merged if p["status"] == "partial")
    empty = sum(1 for p in all_merged if p["status"] == "empty")
    log.info("=" * 60)
    log.info(f"TERMINÉ — {len(all_merged)} POIs")
    log.info(f"  ✓ complete: {complete}")
    log.info(f"  ~ partial:  {partial}")
    log.info(f"  ✗ empty:    {empty}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
