"""Complète les champs manquants Points de vue avec prompts d'inférence améliorés."""
import sys, json, os
if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8',errors='replace')
if hasattr(sys.stderr,'reconfigure'): sys.stderr.reconfigure(encoding='utf-8',errors='replace')
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

import anthropic
from config import OUTPUT_GLOBAL, ANTHROPIC_API_KEY
from dataforseo import search_organic
from scraper_missing import _call_haiku, _snippets_to_text

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
data = json.load(open(OUTPUT_GLOBAL, encoding='utf-8'))

FIELDS = ('orientation','view_description','has_orientation_panel','nb_steps','ideal_weather','altitude_m','storm_interest')

for i, p in enumerate(data):
    if p.get('subcategory') != 'Points de vue': continue
    sp = p.setdefault('specific', {}); st = p.setdefault('specific_status', {})
    missing = [k for k in FIELDS if sp.get(k) is None and st.get(k) != 'manual']
    if not missing: continue

    name    = p['name']
    commune = p.get('commune', '')
    desc    = (p.get('description_long') or p.get('description') or '')
    conseil = (p.get('conseil_planly') or '')
    avis    = ' '.join(r.get('text','') for r in (p.get('reviews') or []) if r.get('text'))
    corpus  = f"Description : {desc}\n\nConseil Planly : {conseil}\n\nAvis : {avis}"

    print(f"\n{name} — manque: {missing}")

    # ── Passe 1 : inférence depuis corpus (avec règles explicites) ──────────
    prompt = f"""Texte sur le point de vue "{name}" ({commune}, côte Atlantique vendéenne) :

{corpus[:7000]}

Règles d'inférence (OBLIGATOIRES) :
- orientation : Si "coucher de soleil" ou "vue sur l'Atlantique" ou "vue sur la mer" → "O". Si "île d'Yeu visible" → "O". Si "panoramique 360°" → "360". Sinon cherche une direction explicite.
- ideal_weather : "coucher de soleil", "beau temps", "lumières dorées" → "beau". "tempête", "grand vent", "gros temps" → "tempete". "vent" seul → "vent". "marée forte", "coefficient" → "vent". "toujours" ou "en toutes saisons" → "all".
- storm_interest : true si "tempête", "vague", "vent fort", "impressionnant", "spectaculaire", "déchaîné" apparaît dans les avis.
- has_orientation_panel : true si "table d'orientation", "panneau", "panneaux d'orientation", "borne" mentionné.
- nb_steps : entier si "marches" ou "escaliers" + un nombre explicite.
- altitude_m : cherche "X mètres", "X m d'altitude", "hauteur X".
- view_description : 1 phrase courte (max 80 chars) sur ce qu'on voit réellement.

Retourne UNIQUEMENT les champs demandés, null si vraiment introuvable même par inférence :
{{{', '.join(f'"{k}": <valeur|null>' for k in missing)}}}"""

    r = _call_haiku(client, prompt, max_tokens=400)
    print(f"  Haiku: {r}")
    if r and isinstance(r, dict):
        src = ['description+avis+inference']
        for k in missing:
            v = r.get(k)
            if v is not None:
                sp[k] = v; st[k] = 'auto'
                print(f"  -> {k} = {v}")

    # ── Passe 2 : SERP pour ce qui manque encore ────────────────────────────
    still = [k for k in missing if sp.get(k) is None]
    if still:
        print(f"  Passe 2 SERP pour: {still}")
        snips = search_organic(
            f'{name} {commune} altitude orientation vue description', depth=6)
        txt = _snippets_to_text(snips, 4000)
        if txt:
            prompt2 = f'Texte sur "{name}" ({commune}) :\n{txt}\n\n'
            prompt2 += 'Règles identiques (orientation: coucher soleil/Atlantique → O, etc.)\n'
            prompt2 += f'{{{", ".join(f"{chr(34)}{k}{chr(34)}: <valeur|null>" for k in still)}}}'
            r2 = _call_haiku(client, prompt2, max_tokens=300)
            print(f"  Haiku2: {r2}")
            if r2 and isinstance(r2, dict):
                for k in still:
                    v = r2.get(k)
                    if v is not None:
                        sp[k] = v; st[k] = 'auto'
                        print(f"  -> {k} = {v}")

    data[i] = p

json.dump(data, open(OUTPUT_GLOBAL,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
print('\nSauvegardé.')
