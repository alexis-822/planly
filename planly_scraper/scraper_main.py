"""
Planly — Script 1 : Pipeline principal
DataForSEO business_info + reviews + images + Wikipedia + Claude enrichissement
Produit output_global.json + fichiers individuels dans output/

Usage:
    python scraper_main.py
    python scraper_main.py --dry-run
    python scraper_main.py --skip-dataforseo
"""
import argparse
import io
import json
import logging
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from config import OUTPUT_DIR, OUTPUT_GLOBAL
from poi_loader import load_pois
from dataforseo import (
    fetch_all_business,
    post_review_tasks, fetch_review_results,
    post_image_tasks, fetch_image_results,
)
from wikipedia_client import fetch_all_wikipedia
from claude_enricher import enrich_all
from merger import merge_poi, save_poi_json, save_global_json
from parking import fetch_all_parkings

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


def run_dataforseo(pois):
    # ÉTAPE 1 — business_info avec retry variantes
    log.info("=" * 60)
    log.info("ÉTAPE 1 — DataForSEO my_business_info")
    log.info("=" * 60)
    business_results = fetch_all_business(pois)
    log.info(f"{len(business_results)}/{len(pois)} POIs avec résultats")

    # ÉTAPE 2 — Reviews
    log.info("=" * 60)
    log.info("ÉTAPE 2 — DataForSEO Google Reviews")
    log.info("=" * 60)
    pois_with_cid = []
    for poi in pois:
        biz = business_results.get(poi["tag"], {})
        if biz.get("cid"):
            pois_with_cid.append({**poi, "cid": biz["cid"]})
    log.info(f"{len(pois_with_cid)} POIs avec cid")

    review_results = {}
    if pois_with_cid:
        review_tags = post_review_tasks(pois_with_cid)
        review_results = fetch_review_results(review_tags)
    log.info(f"{len(review_results)} POIs avec avis")

    # ÉTAPE 3 — Images
    log.info("=" * 60)
    log.info("ÉTAPE 3 — DataForSEO SERP Images")
    log.info("=" * 60)
    image_tags = post_image_tasks(pois)
    main_images = {
        tag: biz.get("main_image")
        for tag, biz in business_results.items()
        if biz.get("main_image")
    }
    photo_results = fetch_image_results(image_tags, main_images)
    log.info(f"{len(photo_results)} POIs avec photos")

    return business_results, review_results, photo_results


def run_parkings(pois, business_results):
    log.info("=" * 60)
    log.info("ÉTAPE 3b — Parkings OSM (Overpass)")
    log.info("=" * 60)
    pois_with_coords = []
    for poi in pois:
        biz = business_results.get(poi["tag"], {})
        lat = biz.get("lat")
        lng = biz.get("lng")
        if lat and lng:
            pois_with_coords.append({"tag": poi["tag"], "lat": lat, "lng": lng})
    log.info(f"{len(pois_with_coords)}/{len(pois)} POIs avec coordonnées")
    parking_results = fetch_all_parkings(pois_with_coords)
    found = sum(1 for v in parking_results.values() if v.get("parking_main"))
    log.info(f"{found}/{len(pois_with_coords)} POIs avec parking trouvé")
    return parking_results


def run_wikipedia(pois):
    log.info("=" * 60)
    log.info("ÉTAPE 4 — Wikipedia FR")
    log.info("=" * 60)
    wiki_results = fetch_all_wikipedia(pois)
    found = sum(1 for v in wiki_results.values() if v)
    log.info(f"{found}/{len(pois)} POIs avec Wikipedia")
    return wiki_results


def run_claude(pois, business_results, review_results, wikipedia_results):
    log.info("=" * 60)
    log.info("ÉTAPE 5 — Claude API enrichissement")
    log.info("=" * 60)
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
    enriched = enrich_all(pois_for_claude)
    log.info(f"{sum(1 for v in enriched.values() if v)}/{len(pois)} POIs enrichis")
    return enriched


def _load_existing() -> dict[str, dict]:
    """Charge les POIs existants depuis output_global.json (pour le resume)."""
    if os.path.exists(OUTPUT_GLOBAL):
        try:
            with open(OUTPUT_GLOBAL, "r", encoding="utf-8") as f:
                existing = json.load(f)
            return {p["id"]: p for p in existing}
        except Exception:
            pass
    return {}


def main():
    parser = argparse.ArgumentParser(description="Planly — Pipeline principal")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-dataforseo", action="store_true")
    parser.add_argument("--subcategory", type=str, default=None,
                        help="Filtrer par sous-catégorie (ex: 'Plages & Côte')")
    parser.add_argument("--no-resume", action="store_true",
                        help="Refaire tous les POIs même ceux déjà scrappés")
    args = parser.parse_args()

    log.info("Chargement des POIs...")
    all_pois = load_pois()
    log.info(f"{len(all_pois)} POIs chargés depuis Excel")

    # Filtre par sous-catégorie
    if args.subcategory:
        all_pois = [p for p in all_pois if p["subcategory"] == args.subcategory]
        log.info(f"{len(all_pois)} POIs après filtre subcategory='{args.subcategory}'")

    # Resume : charger les POIs existants et ne traiter que les nouveaux
    existing = _load_existing()
    if existing and not args.no_resume:
        pois_to_process = [p for p in all_pois if p["tag"] not in existing or existing[p["tag"]].get("status") != "complete"]
        skipped = len(all_pois) - len(pois_to_process)
        if skipped > 0:
            log.info(f"RESUME: {skipped} POIs déjà complets → skip, {len(pois_to_process)} à traiter")
        pois = pois_to_process
    else:
        pois = all_pois

    if args.dry_run:
        for p in pois:
            status = existing.get(p["tag"], {}).get("status", "new")
            print(f"  [{p['tag']}] {p['name']} — {p['subcategory']} — status: {status}")
        log.info(f"{len(pois)} POIs à traiter")
        return

    if not pois:
        log.info("Aucun POI à traiter — tout est déjà complet !")
        return

    business_results = {}
    review_results = {}
    photo_results = {}
    parking_results = {}

    if not args.skip_dataforseo:
        business_results, review_results, photo_results = run_dataforseo(pois)

    parking_results = run_parkings(pois, business_results)
    wikipedia_results = run_wikipedia(pois)
    enriched_results = run_claude(pois, business_results, review_results, wikipedia_results)

    # Fusion & sauvegarde
    log.info("=" * 60)
    log.info("FUSION & SAUVEGARDE")
    log.info("=" * 60)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Merger les nouveaux résultats (en préservant specific/specific_status existants)
    new_merged = []
    for poi in pois:
        tag = poi["tag"]
        merged = merge_poi(
            poi=poi,
            business=business_results.get(tag),
            reviews=review_results.get(tag),
            photos=photo_results.get(tag),
            wikipedia=wikipedia_results.get(tag),
            enriched=enriched_results.get(tag),
            parkings=parking_results.get(tag),
        )
        # Préserver les champs spécifiques déjà remplis par scraper_missing
        if tag in existing:
            old = existing[tag]
            if old.get("specific"):
                merged["specific"] = old["specific"]
            if old.get("specific_status"):
                merged["specific_status"] = old["specific_status"]
        save_poi_json(merged)
        new_merged.append(merged)
        log.info(f"[{tag}] → {merged['status']}")

    # Fusionner avec les existants
    for m in new_merged:
        existing[m["id"]] = m

    # Reconstruire la liste complète (garder l'ordre du Excel)
    all_excel_pois = load_pois()
    all_merged = []
    for p in all_excel_pois:
        if p["tag"] in existing:
            all_merged.append(existing[p["tag"]])

    save_global_json(all_merged)

    # Résumé
    complete = sum(1 for p in all_merged if p["status"] == "complete")
    partial = sum(1 for p in all_merged if p["status"] == "partial")
    empty = sum(1 for p in all_merged if p["status"] == "empty")
    log.info("=" * 60)
    log.info(f"TERMINÉ — {len(new_merged)} nouveaux + {len(all_merged) - len(new_merged)} existants = {len(all_merged)} total")
    log.info(f"  ✓ complete: {complete}")
    log.info(f"  ~ partial:  {partial}")
    log.info(f"  ✗ empty:    {empty}")
    log.info(f"  → {OUTPUT_GLOBAL}")
    log.info("=" * 60)

    _update_dashboard(all_merged)


def _update_dashboard(data):
    """Injecte le JSON dans dashboard.html."""
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
        log.info(f"Dashboard mis à jour avec {len(data)} POIs")
    except Exception as e:
        log.warning(f"Impossible de mettre à jour le dashboard: {e}")


if __name__ == "__main__":
    main()
