import logging
import math
import requests

log = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance en mètres entre deux points GPS."""
    R = 6371000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _query_overpass(lat: float, lng: float, radius: int) -> list[dict]:
    """Requête Overpass pour trouver les parkings autour d'un point (avec retry)."""
    import time
    query = f"""
    [out:json][timeout:10];
    (
      node["amenity"="parking"](around:{radius},{lat},{lng});
      way["amenity"="parking"](around:{radius},{lat},{lng});
      relation["amenity"="parking"](around:{radius},{lat},{lng});
    );
    out center tags;
    """
    for attempt in range(3):
        try:
            resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=15)
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                log.info(f"    Overpass rate limit, attente {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except requests.exceptions.Timeout:
            time.sleep(3)
        except Exception as e:
            if attempt < 2:
                time.sleep(5)
            else:
                raise
    return []


def _parse_parking(element: dict, poi_lat: float, poi_lng: float) -> dict:
    """Parse un élément Overpass en dict parking."""
    tags = element.get("tags", {})

    # Coordonnées : node = lat/lon, way/relation = center
    if element.get("type") == "node":
        plat = element.get("lat")
        plng = element.get("lon")
    else:
        center = element.get("center", {})
        plat = center.get("lat")
        plng = center.get("lon")

    if plat is None or plng is None:
        return None

    # Nom
    name = tags.get("name") or tags.get("description") or "Parking sans nom"

    # Gratuit ?
    fee = tags.get("fee", "").lower()
    is_free = fee in ("no", "0") if fee else None

    # Places handicapées
    disabled = tags.get("capacity:disabled") or tags.get("wheelchair")
    if disabled and disabled.isdigit():
        disabled_spaces = int(disabled)
    elif disabled in ("yes",):
        disabled_spaces = True
    else:
        disabled_spaces = None

    distance = round(_haversine(poi_lat, poi_lng, plat, plng))

    return {
        "nom": name,
        "lat": plat,
        "lng": plng,
        "distance_meters": distance,
        "is_free": is_free,
        "disabled_spaces": disabled_spaces,
    }


def get_nearby_parkings(lat: float, lng: float) -> dict:
    """Trouve les parkings proches d'un POI.

    Essaie 500m, puis 1000m si rien trouvé.

    Returns:
        {
            "parking_main": {nom, lat, lng, distance_meters, is_free, disabled_spaces} | None,
            "parking_others": [{nom, lat, lng, distance_meters, is_free}]
        }
    """
    if lat is None or lng is None:
        return {"parking_main": None, "parking_others": []}

    for radius in (500, 1000):
        try:
            elements = _query_overpass(lat, lng, radius)
        except Exception as e:
            log.warning(f"Overpass erreur (radius={radius}m): {e}")
            continue

        parkings = []
        for el in elements:
            p = _parse_parking(el, lat, lng)
            if p:
                parkings.append(p)

        if parkings:
            # Trier par distance
            parkings.sort(key=lambda p: p["distance_meters"])

            main = parkings[0]
            others = []
            for p in parkings[1:2]:  # 1 seul autre parking
                others.append({
                    "nom": p["nom"],
                    "lat": p["lat"],
                    "lng": p["lng"],
                    "distance_meters": p["distance_meters"],
                    "is_free": p["is_free"],
                })

            log.info(f"  Parkings: {len(parkings)} trouvés (radius={radius}m), main={main['nom']} ({main['distance_meters']}m)")
            return {"parking_main": main, "parking_others": others}

        if radius == 500:
            log.info(f"  Parkings: 0 dans 500m, essai 1000m...")

    log.info(f"  Parkings: aucun trouvé dans 1000m")
    return {"parking_main": None, "parking_others": []}


def fetch_all_parkings(pois_with_coords: list[dict]) -> dict[str, dict]:
    """Récupère les parkings pour tous les POIs ayant des coordonnées.

    Args:
        pois_with_coords: list de dicts avec 'tag', 'lat', 'lng'

    Returns:
        dict tag -> {parking_main, parking_others}
    """
    import time
    results = {}
    for i, poi in enumerate(pois_with_coords):
        tag = poi["tag"]
        lat = poi.get("lat")
        lng = poi.get("lng")
        if lat is None or lng is None:
            results[tag] = {"parking_main": None, "parking_others": []}
            continue
        log.info(f"[{tag}] Recherche parkings ({lat}, {lng})")
        results[tag] = get_nearby_parkings(lat, lng)
        # Pause entre les requêtes pour éviter le rate limit Overpass
        if i < len(pois_with_coords) - 1:
            time.sleep(3)
    return results
