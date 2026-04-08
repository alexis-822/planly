"""Transforme les POIs scrappés en format planly-full.html et les injecte."""
import json
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GLOBAL_JSON = os.path.join(SCRIPT_DIR, "output_global.json")
PLANLY_HTML = os.path.join(SCRIPT_DIR, "..", "planly-full.html")

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


def make_quick_specs(p):
    specs = []
    subcat = p.get("subcategory", "")
    specific = p.get("specific", {}) or {}

    if subcat == "Plages & C\u00f4te":
        bt = specific.get("beach_type")
        if bt:
            specs.append({"label": bt.capitalize(), "icon": "\U0001f3d6\ufe0f", "cls": ""})
        if specific.get("supervised"):
            specs.append({"label": "Surveill\u00e9e", "icon": "\U0001f3ca", "cls": "positive"})
        if specific.get("showers"):
            specs.append({"label": "Douches", "icon": "\U0001f6bf", "cls": "positive"})
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
            imgs.append("planly_scraper/" + ph)
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
    parking = {
        "nom": pm.get("nom", "Non renseign\u00e9"),
        "lat": pm.get("lat") or p.get("lat") or 0,
        "lng": pm.get("lng") or p.get("lng") or 0,
        "autres": [],
    }
    for po in (p.get("parking_others") or [])[:2]:
        dist_m = po.get("distance_meters", 0) or 0
        dist_txt = f"{max(1, int(dist_m / 80))} min \u00e0 pied" if dist_m else "?"
        parking["autres"].append({"nom": po.get("nom", "?"), "dist": dist_txt})

    # Conseil
    conseil_txt = p.get("conseil_planly", "") or ""
    conseil = {
        "positif": conseil_txt[:200] if conseil_txt else "Un lieu \u00e0 d\u00e9couvrir.",
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
        ia_pill = "\U0001f4a1 Planly : " + conseil_txt[:60]

    return {
        "imgs": imgs,
        "name": p.get("name", ""),
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
        "pricing": {
            "adult": p.get("price_adult", 0) or 0,
            "child": p.get("price_child", 0) or 0,
            "is_free": (p.get("price_range", "") == "gratuit"),
        },
        "duration": duration,
        "distance": {"km": "?", "min": {"voiture": "?", "pied": "?", "velo": "?"}},
        "affluence": {"label": "Normal", "color": "green"},
        "instant": None,
        "quickSpecs": make_quick_specs(p),
        "avis": avis,
        "parking": parking,
        "location": {"lat": p.get("lat") or 0, "lng": p.get("lng") or 0},
        "conseil": conseil,
        "veto": None,
    }


def main():
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
    js_block = "var POIS=" + js_data + ";"

    # Read planly-full.html
    with open(PLANLY_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    # Replace POIS array
    start_marker = "var POIS=["
    start = html.index(start_marker)
    end = html.index("];", start) + 2
    html = html[:start] + js_block + html[end:]

    with open(PLANLY_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"{len(converted)} POIs injectes dans planly-full.html")
    for c in converted:
        print(f"  {c['name']}")


if __name__ == "__main__":
    main()
