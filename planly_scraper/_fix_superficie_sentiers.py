"""Scrape superficie_ha + sentiers_km_total pour les POIs Forêts & Nature manquants."""
import sys, io, json, os, requests, re
if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8',errors='replace')
if hasattr(sys.stderr,'reconfigure'): sys.stderr.reconfigure(encoding='utf-8',errors='replace')
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

import anthropic
from config import OUTPUT_GLOBAL, ANTHROPIC_API_KEY
from dataforseo import search_organic
from scraper_missing import _call_haiku, _snippets_to_text

from bs4 import BeautifulSoup

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
data = json.load(open(OUTPUT_GLOBAL, encoding='utf-8'))

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'fr-FR,fr;q=0.9',
}

def fetch_text(url, max_chars=6000):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        return soup.get_text(' ', strip=True)[:max_chars]
    except Exception as e:
        print(f'  fetch failed {url[:60]}: {e}')
        return ''

for i, p in enumerate(data):
    if p.get('subcategory') != 'Forêts & Nature':
        continue
    sp = p.setdefault('specific', {})
    st = p.setdefault('specific_status', {})
    name = p['name']

    missing = [k for k in ('superficie_ha', 'sentiers_km_total')
               if sp.get(k) is None]
    if not missing:
        print(f'{name}: déjà complet')
        continue

    print(f'\n{name} — manque: {missing}')
    text, sources = '', []

    # 1. ONF si disponible
    website = p.get('website') or ''
    if 'onf.fr' in website:
        t = fetch_text(website)
        if t:
            text = t; sources = [website]
            print(f'  source: ONF {website[:60]}')

    # 2. Wikipedia
    if not text:
        snips = search_organic(f'{name} wikipedia superficie hectares sentiers km', depth=5)
        wiki = next((s['url'] for s in snips if 'wikipedia.org' in s.get('url','')), None)
        if wiki:
            t = fetch_text(wiki)
            if t:
                text = t; sources = [wiki]
                print(f'  source: Wikipedia {wiki[:60]}')

    # 3. SERP snippets
    if not text:
        snips = search_organic(f'{name} superficie hectares sentiers km randonnee', depth=8)
        text = _snippets_to_text(snips, 6000)
        sources = [s.get('url','') for s in snips[:3]]
        print(f'  source: SERP snippets')

    # 4. Recherche ONF spécifique si aucun résultat
    if not text:
        snips = search_organic(f'site:onf.fr {name} forêt superficie sentiers', depth=5)
        if snips:
            url = snips[0].get('url','')
            t = fetch_text(url)
            if t:
                text = t; sources = [url]

    if not text:
        print(f'  aucune source trouvée')
        continue

    fields_str = ', '.join(f'"{k}": <int|null>' for k in missing)
    prompt = (
        f'Texte sur "{name}" :\n\n{text[:5000]}\n\n'
        f'Extrais UNIQUEMENT (NE PAS inventer si absent):\n'
        f'- superficie_ha : nombre entier juste avant "hectares" ou "ha"\n'
        f'- sentiers_km_total : nombre entier juste avant "km de sentiers" ou "km de chemins" ou "km balisés"\n'
        f'{{{fields_str}}}'
    )
    r = _call_haiku(client, prompt)
    print(f'  Haiku: {r}')
    if r and isinstance(r, dict):
        for k in missing:
            v = r.get(k)
            if v is not None:
                sp[k] = v
                st[k] = 'auto'
                print(f'  -> {k} = {v}')
            else:
                st[k] = 'empty'
    data[i] = p

json.dump(data, open(OUTPUT_GLOBAL,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
print('\nSauvegardé.')
