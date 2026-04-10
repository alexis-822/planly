"""Lance process_forets_nature uniquement sur Forêt Domaniale d'Olonne."""
import sys, io, json, os
# Reconfigure stdout/stderr pour UTF-8 sans fermer le buffer
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

data = json.load(open(OUTPUT_GLOBAL, encoding="utf-8"))

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
report = []

for i, poi in enumerate(data):
    if "Forêt Domaniale d'Olonne" in poi.get("name", ""):
        print(f"\n=== {poi['name']} ===")
        data[i] = process_forets_nature(client, poi, report)
        sp = data[i].get("specific", {})
        trails = sp.get("trails", [])
        print(f"\nRésultat : {len(trails)} trails")
        for t in trails:
            print(f"  - {t.get('name')} | {t.get('type')} | {t.get('distance_km')}km | {t.get('duration_min')}min | diff:{t.get('difficulty')} | url:{t.get('trail_url','')[:60] if t.get('trail_url') else None}")
        break

json.dump(data, open(OUTPUT_GLOBAL, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\nSauvegardé.")
