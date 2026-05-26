"""Transforme les POIs scrappés en format planly-full.html et les injecte."""
import json
import os
import sys
import io
import re
import math
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Ref : 1 Av. Georges Pompidou, Les Sables-d'Olonne
REF_LAT, REF_LNG = 46.4977749, -1.7823345

def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def compute_distance(lat, lng):
    if not lat or not lng:
        return {"km": "?", "min": {"voiture": "?"}}
    km = haversine_km(REF_LAT, REF_LNG, lat, lng)
    km_route = round(km * 1.3, 1)  # x1.3 sinuosite cote vendeenne
    min_voiture = max(1, round(km_route / 45 * 60))  # 45 km/h moy
    return {"km": km_route, "min": {"voiture": min_voiture}}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GLOBAL_JSON = os.path.join(SCRIPT_DIR, "output_global.json")
PLANLY_HTML = os.path.join(SCRIPT_DIR, "..", "planly-full.html")
POIS_JS = os.path.join(SCRIPT_DIR, "..", "pois.js")

CAT_MAP = {
    "Nature & Grand Air": "🌊",
    "Sport & Aventure": "🏃",
    "Patrimoine": "🏛️",
    "Art de vivre": "🍽️",
    "Parcs & Loisirs": "🎡",
    "Sorties & Détente": "🎬",
}

SUBCAT_CAT_MAP = {
    "Plages & Côte": "plage",
    "Forêts & Nature": "nature",
    "Points de vue": "pointdevue",
    "Balades & Promenades": "balade",
    "Nautisme": "activite",
    "Villages & Sites": "patrimoine",
    "Châteaux & Monuments": "patrimoine",
    "Musées & Culture": "culture",
    "Ports & Littoral": "port",
}


def make_budget(p):
    pa = p.get("price_adult", 0) or 0
    pr = p.get("price_range", "gratuit") or "gratuit"
    if pr == "gratuit" or pa == 0:
        return "\u20ac Gratuit", "free"
    elif pa <= 10:
        return "\u20ac Petit budget", "paid"
    elif pa <= 25:
        return "\u20ac\u20ac Mod\u00e9r\u00e9", "paid"
    return "\u20ac\u20ac\u20ac Premium", "paid"


BEACH_TYPE_LABELS = {
    "sable_fin": "Sable fin",
    "sable fin": "Sable fin",
    "sable_normal": "Sable",
    "sable": "Sable",
    "galets": "Galets",
    "sable_galets": "Sable & galets",
    "mixte": "Sable & galets",
    "sable galets": "Sable & galets",
    "rochers": "Rochers",
    "sable_rochers": "Sable & rochers",
    "sable rochers": "Sable & rochers",
}

MONTHS_FR = {
    "janvier": "jan.", "février": "fév.", "mars": "mars", "avril": "avr.",
    "mai": "mai", "juin": "juin", "juillet": "juil.", "août": "août",
    "septembre": "sept.", "octobre": "oct.", "novembre": "nov.", "décembre": "déc."
}


def _extract_month(s):
    if not s:
        return None
    s = s.lower()
    for m, abbr in MONTHS_FR.items():
        if m in s:
            return abbr
    return None


def _extract_peak_hours(hours_str):
    """Extrait les horaires de pointe (juil-août) d'une chaîne d'horaires."""
    if not hours_str:
        return None
    # Pattern horaires : 10h30-19h ou 14h à 18h30
    pat = r'\d{1,2}h\d{0,2}[\s]*[-–à]\s*\d{1,2}h\d{0,2}'
    # 1. Cherche les horaires juste après "juillet" ou "août"
    m = re.search(r'(?:juil|ao[uû]t)[^;,\n]*?(' + pat + ')', hours_str, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 2. Cherche les horaires avant "juillet" ou "août" sur la même portion
    m = re.search(r'(' + pat + r')[^;,\n]*?(?:juil|ao[uû]t)', hours_str, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 3. Fallback : premier horaire trouvé
    patterns = re.findall(pat, hours_str)
    return patterns[0].strip() if patterns else None


def make_beach_data(specific):
    """Construit le sous-objet beach pour un POI plage."""
    if not specific:
        return None
    bt_raw = (specific.get("beach_type") or "").lower().strip()
    type_label = BEACH_TYPE_LABELS.get(bt_raw) or (bt_raw.capitalize() if bt_raw else "—")
    supervised = bool(specific.get("supervised"))
    sup_hours = _extract_peak_hours(specific.get("supervised_hours"))
    period_start = _extract_month(specific.get("supervised_start"))
    period_end = _extract_month(specific.get("supervised_end"))
    period = (period_start + "→" + period_end) if (period_start and period_end) else None
    wave_profile = (specific.get("wave_profile") or "").lower().strip() or None
    return {
        "type_label": type_label,
        "supervised": supervised,
        "hours": sup_hours,
        "period": period,
        "wave_profile": wave_profile,
        "naturist": bool(specific.get("naturist")),
        "beach_bar": bool(specific.get("beach_bar")),
        "dogs": bool(specific.get("dogs_allowed_beach")),
        "tide_sensitive": bool(specific.get("tide_sensitive")),
        "showers": bool(specific.get("showers")),
    }


def make_quick_specs(p):
    specs = []
    subcat = p.get("subcategory", "")
    specific = p.get("specific", {}) or {}

    if subcat == "Plages & C\u00f4te":
        # Beach type — label enrichi (affiché sur la card swipe, pas dans le ribbon detail)
        bt_raw = (specific.get("beach_type") or "").lower().strip()
        bt_label = BEACH_TYPE_LABELS.get(bt_raw) or (bt_raw.capitalize() if bt_raw else None)
        if bt_label:
            specs.append({"label": bt_label, "icon": "\U0001f3d6\ufe0f", "cls": ""})
        if specific.get("supervised"):
            specs.append({"label": "Surveill\u00e9e", "icon": "\U0001f3ca", "cls": "positive"})
        if specific.get("showers"):
            specs.append({"label": "Douches", "icon": "\U0001f6bf", "cls": "positive"})
        wave = (specific.get("wave_profile") or "").lower()
        if wave in ("modéré", "modere", "sportif", "fort"):
            wave_label = "Mer sportive" if wave in ("sportif", "fort") else "Vagues mod\u00e9r\u00e9es"
            specs.append({"label": wave_label, "icon": "\U0001f30a", "cls": "warning"})
    elif subcat in ("For\u00eats & Nature", "Balades & Promenades"):
        diff = specific.get("difficulty")
        if diff:
            cls = "warning" if diff == "difficile" else ""
            specs.append({"label": diff.capitalize(), "icon": "\U0001f4aa", "cls": cls})
        if specific.get("stroller_ok"):
            specs.append({"label": "Poussette OK", "icon": "\U0001f476", "cls": "positive"})
        if specific.get("bike_allowed"):
            specs.append({"label": "V\u00e9lo OK", "icon": "\U0001f6b2", "cls": "positive"})
    elif subcat == "Villages & Sites":
        hp = specific.get("historical_period")
        if hp:
            specs.append({"label": hp, "icon": "\U0001f4dc", "cls": ""})
        if specific.get("guided_visit"):
            specs.append({"label": "Visite guid\u00e9e", "icon": "\U0001f399\ufe0f", "cls": "positive"})
        if specific.get("free_entry"):
            specs.append({"label": "Entr\u00e9e libre", "icon": "\U0001f39f\ufe0f", "cls": "positive"})
    elif subcat == "Points de vue":
        if specific.get("panoramic"):
            specs.append({"label": "Panoramique", "icon": "\U0001f304", "cls": "positive"})
        diff = specific.get("difficulty")
        if diff:
            specs.append({"label": diff.capitalize(), "icon": "\U0001f4aa", "cls": ""})
    elif subcat == "Ports & Littoral":
        specs.append({"label": "Bord de mer", "icon": "\u2693", "cls": ""})

    acc = p.get("accessibility", {}) or {}
    if acc.get("wheelchair"):
        specs.append({"label": "Acc\u00e8s PMR", "icon": "\u267f", "cls": "positive"})

    # Fallback: use tags
    if len(specs) < 2:
        for t in (p.get("tags") or [])[:4 - len(specs)]:
            specs.append({"label": t.capitalize(), "icon": "\U0001f4cc", "cls": ""})

    return specs[:4]


def convert_poi(p):
    emoji = CAT_MAP.get(p.get("category", ""), "\U0001f4cd")
    cat_label = emoji + " " + (p.get("category") or "Autre")

    budget_badge, budget_class = make_budget(p)

    # Photos
    photos = p.get("photos", []) or []
    imgs = []
    for ph in photos[:3]:
        if not ph.startswith("http"):
            imgs.append("planly_scraper/" + ph + "?v=" + BUILD_VERSION)
        else:
            imgs.append(ph)
    if not imgs:
        imgs = ["https://placehold.co/700x400/e0e0e0/999?text=Photo+manquante"]

    # Reviews
    reviews_raw = p.get("reviews", []) or []
    avis = []
    for r in reviews_raw[:3]:
        txt = r.get("text", "")
        if len(txt) > 150:
            txt = txt[:147] + "..."
        date_raw = r.get("date", "")
        avis.append({"txt": txt, "date": date_raw[:10] if date_raw else ""})
    if not avis:
        avis = [{"txt": "Aucun avis disponible.", "date": ""}]

    # Parking
    pm = p.get("parking_main") or {}
    poi_lat = p.get("lat") or 0
    poi_lng = p.get("lng") or 0
    parking = {
        "nom": pm.get("nom", "Parking \u00e0 proximit\u00e9"),
        "lat": pm.get("lat") or poi_lat,
        "lng": pm.get("lng") or poi_lng,
        "autres": [],
    }
    for po in (p.get("parking_others") or [])[:2]:
        dist_m = po.get("distance_meters", 0) or 0
        dist_txt = f"{max(1, int(dist_m / 80))} min \u00e0 pied" if dist_m else "?"
        parking["autres"].append({"nom": po.get("nom", "Parking"), "dist": dist_txt, "lat": po.get("lat", poi_lat), "lng": po.get("lng", poi_lng)})
    # Garantir toujours un 2e parking : fallback Google Maps recherche \u00e0 proximit\u00e9
    if not parking["autres"]:
        parking["autres"].append({
            "nom": "Rechercher un parking proche",
            "dist": "",
            "lat": poi_lat,
            "lng": poi_lng,
            "gmaps_search": True,
        })

    # Conseil
    conseil_txt = p.get("conseil_planly", "") or ""
    conseil = {
        "positif": conseil_txt if conseil_txt else "Un lieu \u00e0 d\u00e9couvrir.",
        "attention": None,
        "verdict": "Bonne visite !",
    }

    notoriety = p.get("notoriety", "connu")
    is_inco = notoriety == "incontournable"

    duration = p.get("duration_min", 60) or 60
    desc_short = (p.get("description_short") or "")[:100]
    desc_long = p.get("description_long") or ""

    ia_pill = None
    if conseil_txt:
        # Tronque à 90 chars sur limite de mot, sans couper en plein milieu
        pill_max = 90
        pill_txt = conseil_txt if len(conseil_txt) <= pill_max else conseil_txt[:pill_max].rsplit(" ", 1)[0] + "…"
        ia_pill = "\U0001f4a1 " + pill_txt

    specific = p.get("specific", {}) or {}
    beach = make_beach_data(specific) if p.get("subcategory") == "Plages & Côte" else None

    return {
        "imgs": imgs,
        "name": p.get("name", ""),
        "commune": p.get("commune", ""),
        "cat": cat_label,
        "note": str(p.get("rating") or "?"),
        "budgetBadge": budget_badge,
        "budgetClass": budget_class,
        "trajet": {"voiture": "? min", "pied": "? min", "velo": "? min"},
        "iaPill": ia_pill,
        "iaWarn": False,
        "desc": desc_short,
        "inco": is_inco,
        "accroche": desc_short[:80],
        "descLong": desc_long,
        "category": SUBCAT_CAT_MAP.get(p.get("subcategory", ""), "autre"),
        "subcategory": p.get("subcategory", ""),
        "pricing": {
            "adult": p.get("price_adult", 0) or 0,
            "child": p.get("price_child", 0) or 0,
            "is_free": (p.get("price_range", "") == "gratuit"),
        },
        "duration": duration,
        "distance": compute_distance(p.get("lat"), p.get("lng")),
        "affluence": {"label": "Normal", "color": "green"},
        "instant": None,
        "quickSpecs": make_quick_specs(p),
        "avis": avis,
        "parking": parking,
        "location": {"lat": p.get("lat") or 0, "lng": p.get("lng") or 0},
        "conseil": conseil,
        "beach": beach,
        "specific": specific,
        "veto": None,
    }


def main():
    global BUILD_VERSION
    BUILD_VERSION = datetime.now().strftime("%Y%m%d%H%M")

    with open(GLOBAL_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Filter POIs >= 85% essential fields
    essential = ["lat", "lng", "description_short", "description_long", "photos", "tags", "rating", "conseil_planly"]
    converted = []
    for p in data:
        filled = sum(1 for f in essential if p.get(f))
        pct = filled / len(essential) * 100
        if pct >= 85:
            converted.append(convert_poi(p))

    # Build JS
    js_data = json.dumps(converted, ensure_ascii=False, indent=2)
    js_block = "var POIS=" + js_data + ";\n"

    # Écrire dans pois.js
    with open(POIS_JS, "w", encoding="utf-8") as f:
        f.write(js_block)

    # Mettre à jour le tag <script src="pois.js?v=..."> dans le HTML
    with open(PLANLY_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    # Remplace pois.js?v=... ou pois.js (sans version) par la version actuelle
    html_new = re.sub(r'<script src="pois\.js(?:\?v=[^"]*)?"></script>',
                      f'<script src="pois.js?v={BUILD_VERSION}"></script>', html)

    # Ajouter meta no-store si absent
    if 'http-equiv="Cache-Control"' not in html_new:
        html_new = html_new.replace(
            '<meta charset="UTF-8">',
            '<meta charset="UTF-8">\n<meta http-equiv="Cache-Control" content="no-store">'
        )

    if html_new != html:
        with open(PLANLY_HTML, "w", encoding="utf-8") as f:
            f.write(html_new)
        print(f"planly-full.html mis a jour (pois.js?v={BUILD_VERSION})")

    print(f"{len(converted)} POIs injectes dans pois.js")
    for c in converted:
        print(f"  {c['name']}")


if __name__ == "__main__":
    main()
