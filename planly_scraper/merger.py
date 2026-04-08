import json
import logging
import os
from datetime import datetime, timezone
from config import OUTPUT_DIR, OUTPUT_GLOBAL

log = logging.getLogger(__name__)


def merge_poi(
    poi: dict,
    business: dict | None,
    reviews: list[dict] | None,
    photos: list[str] | None,
    wikipedia: str | None,
    enriched: dict | None,
    parkings: dict | None = None,
) -> dict:
    """Fusionne toutes les sources de données en un JSON final pour un POI."""
    biz = business or {}
    enr = enriched or {}

    now = datetime.now(timezone.utc).isoformat()
    scraped_at = now if business else None
    enriched_at = now if enriched else None

    # Déterminer le statut
    if business and enriched:
        status = "complete"
    elif business or enriched:
        status = "partial"
    else:
        status = "empty"

    return {
        # Identité
        "id": poi["tag"],
        "name": poi["name"],  # Toujours garder le nom du Excel
        "name_google": biz.get("name_google"),
        "category": poi["category"],
        "subcategory": poi["subcategory"],
        "commune": poi["commune"],
        "zone": None,
        "poi_format": "poi",

        # DataForSEO
        "lat": biz.get("lat"),
        "lng": biz.get("lng"),
        "address": biz.get("address"),
        "phone": biz.get("phone"),
        "website": biz.get("website"),
        "rating": biz.get("rating"),
        "reviews_count": biz.get("reviews_count"),
        "rating_distribution": biz.get("rating_distribution"),
        "opening_hours": biz.get("opening_hours"),
        "popular_times": biz.get("popular_times"),
        "price_level": biz.get("price_level"),
        "photos": photos or ([biz["main_image"]] if biz.get("main_image") else []),
        "reviews": reviews or [],
        "place_topics": biz.get("place_topics"),
        "booking_url": biz.get("booking_url"),
        "cid": biz.get("cid"),
        "place_id": biz.get("place_id"),

        # Wikipedia
        "wikipedia_description": wikipedia,

        # Claude enrichissement
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

        # Champs spécifiques (à remplir par scraper_missing.py ou manuellement)
        "specific": {},
        "specific_status": {},  # par champ: "auto" | "uncertain" | "empty" | "manual"

        # Parkings
        "parking_main": (parkings or {}).get("parking_main"),
        "parking_others": (parkings or {}).get("parking_others", []),

        # Meta
        "scraped_at": scraped_at,
        "enriched_at": enriched_at,
        "status": status,
    }


def save_poi_json(poi_data: dict) -> str:
    """Sauvegarde un POI en fichier JSON individuel."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{poi_data['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(poi_data, f, ensure_ascii=False, indent=2)
    return path


def save_global_json(all_pois: list[dict]) -> str:
    """Sauvegarde tous les POIs en un seul fichier JSON."""
    with open(OUTPUT_GLOBAL, "w", encoding="utf-8") as f:
        json.dump(all_pois, f, ensure_ascii=False, indent=2)
    log.info(f"JSON global sauvegardé : {OUTPUT_GLOBAL} ({len(all_pois)} POIs)")
    return OUTPUT_GLOBAL


def merge_and_save_all(
    pois: list[dict],
    business_results: dict[str, dict],
    review_results: dict[str, list],
    photo_results: dict[str, list],
    wikipedia_results: dict[str, str | None],
    enriched_results: dict[str, dict | None],
) -> list[dict]:
    """Fusionne et sauvegarde tous les POIs."""
    all_merged = []
    for poi in pois:
        tag = poi["tag"]
        merged = merge_poi(
            poi=poi,
            business=business_results.get(tag),
            reviews=review_results.get(tag),
            photos=photo_results.get(tag),
            wikipedia=wikipedia_results.get(tag),
            enriched=enriched_results.get(tag),
        )
        save_poi_json(merged)
        all_merged.append(merged)
        log.info(f"[{tag}] → {merged['status']}")

    save_global_json(all_merged)
    return all_merged
