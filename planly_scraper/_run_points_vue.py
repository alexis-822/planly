"""Lance process_points_de_vue sur tous les POIs Points de vue."""
import sys, json, os
if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8',errors='replace')
if hasattr(sys.stderr,'reconfigure'): sys.stderr.reconfigure(encoding='utf-8',errors='replace')
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

import anthropic
from config import OUTPUT_GLOBAL, ANTHROPIC_API_KEY
from scraper_missing import process_points_de_vue

data = json.load(open(OUTPUT_GLOBAL, encoding='utf-8'))
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
report = []

NEW_KEYS = ('altitude_m','orientation','view_description','storm_interest',
            'has_orientation_panel','nb_steps','ideal_weather')

for i, poi in enumerate(data):
    if poi.get('subcategory') != 'Points de vue':
        continue
    # Reset les nouveaux champs uniquement
    sp = poi.setdefault('specific', {})
    st = poi.setdefault('specific_status', {})
    for k in NEW_KEYS:
        sp.pop(k, None); st.pop(k, None)

    data[i] = process_points_de_vue(client, poi, report)
    sp2 = data[i].get('specific', {})
    print(f"\n{poi['name']}")
    for k in NEW_KEYS:
        print(f'  {k}: {sp2.get(k)}')

json.dump(data, open(OUTPUT_GLOBAL, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('\nSauvegardé.')
