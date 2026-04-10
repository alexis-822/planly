"""Lance process_forets_nature sur plusieurs POIs Forêts & Nature."""
import sys, io, json, os
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import anthropic
from config import OUTPUT_GLOBAL, ANTHROPIC_API_KEY
from scraper_missing import process_forets_nature

# POIs à traiter (nom partiel suffit)
TARGETS = [
    "Marais Salants",
    "Lac de Tanchet",
    "Réserve",
]

data = json.load(open(OUTPUT_GLOBAL, encoding="utf-8"))
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
report = []

for i, poi in enumerate(data):
    name = poi.get("name", "")
    subcat = poi.get("subcategory", "")
    if subcat != "Forêts & Nature":
        continue
    if not any(t.lower() in name.lower() for t in TARGETS):
        continue

    # Reset trails pour forcer re-scrape avec le nouveau process
    sp = poi.setdefault("specific", {})
    st = poi.setdefault("specific_status", {})
    for k in ("trails", "trails_display", "nb_parcours"):
        sp.pop(k, None)
        st.pop(k, None)

    print(f"\n{'='*60}")
    print(f"=== {name} ===")
    print(f"  alltrails_url: {sp.get('alltrails_url')}")
    print(f"  komoot_url: {sp.get('komoot_url')}")
    data[i] = process_forets_nature(client, poi, report)
    sp2 = data[i].get("specific", {})
    trails = sp2.get("trails", [])
    print(f"\n  Résultat : {len(trails)} trails")
    for t in trails:
        url_short = (t.get("trail_url") or "")[:55]
        print(f"    - {t.get('name')} | {t.get('type')} | {t.get('distance_km')}km | {t.get('duration_min')}min | diff:{t.get('difficulty')} | {url_short}")

json.dump(data, open(OUTPUT_GLOBAL, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n\nTous sauvegardés.")
