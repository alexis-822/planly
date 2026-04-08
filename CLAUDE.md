# Planly — App de découverte touristique (Vendée / Pays de la Loire)

## Ce qu'on fait
App mobile de découverte de POIs touristiques avec swipe cards (type Tinder).
Pipeline Python pour scraper, enrichir et structurer les données POI.
Prototype HTML mobile-first, objectif : migration React Native + Supabase.

## Stack
- **Pipeline scraping** : Python 3.13, requests, openpyxl, anthropic SDK
- **APIs** : DataForSEO (Google Business/Reviews/Images), Overpass (parkings OSM), Wikipedia FR, Claude API
- **Prototype** : HTML/CSS/JS vanilla, mobile-first 390px
- **Design system** : Fraunces (titres, serif) + DM Sans (corps, sans-serif)
- **Couleurs** : `--brand:#428CE3`, `--bg:#FCF8ED`, `--tx:#1A1A18`

## Architecture & Fichiers

### Racine
| Fichier | Rôle |
|---------|------|
| `planly_poi_types.xlsx` | Liste maître des 97 POIs (catégorie, sous-catégorie, nom, commune) |
| `planly-full.html` | Prototype app mobile (swipe cards, fiches, filtres, onboarding) |
| `dashboard.html` | Dashboard complétion POIs (données JSON embarquées) |
| `champs_manquants_villages.xlsx` | Champs manquants Villages & Sites (46 champs) |
| `server.py` | Serveur HTTP local no-cache (port 8080) pour test mobile |
| `CLAUDE.md` | Ce fichier — instructions projet |

### Pipeline principal — `planly_scraper/scraper_main.py`
Script orchestrateur en 8 étapes :
1. **Chargement** (`poi_loader.py`) — Lit le Excel, génère un tag/slug par POI
2. **DataForSEO business_info** (`dataforseo.py`) — Fiche Google Business (lat/lng, adresse, tel, rating, horaires). Fallback Google Maps Live
3. **DataForSEO reviews** — 5 derniers avis Google via CID
4. **DataForSEO images** — Jusqu'à 3 photos via SERP Images
5. **Parkings** (`parking.py`) — Overpass API (OSM), rayon 500m/1000m
6. **Wikipedia** (`wikipedia_client.py`) — Résumé FR (500 chars max)
7. **Claude enrichissement** (`claude_enricher.py`) — Sonnet 4.6 : descriptions, tags, audience, durée, accessibilité, conseil_planly, notoriété
8. **Fusion** (`merger.py`) — Assemble toutes les sources → JSON final par POI

Le script supporte `--resume` (ne re-traite pas les POIs "complete") et `--subcategory` (filtre).

### Scripts complémentaires — `planly_scraper/`
| Script | Rôle |
|--------|------|
| `scraper_missing.py` | Remplissage champs manquants (SERP organic + Claude Haiku extraction) |
| `download_images.py` | Télécharge toutes les images en local (`images/{tag}/photo_N.ext`) |
| `inject_pois.py` | Transforme output_global.json → format JS et injecte dans planly-full.html |
| `import_missing.py` | Import depuis Excel champs_manquants |
| `complete_schema.py` | Schéma complet des champs |

### Champs spécifiques par sous-catégorie
Définis dans `scraper_missing.py` (dict `SPECIFIC_FIELDS`) :
- **Plages & Côte** : beach_type, supervised, showers, wave_profile, naturist, beach_bar
- **Forêts & Nature** : terrain_type, difficulty, stroller_ok, bike_allowed, shade_level
- **Points de vue** : terrain_type, difficulty, best_time, panoramic
- **Balades & Promenades** : distance_km, difficulty, stroller_ok, bike_allowed, loop
- **Villages & Sites** : historical_period, guided_visit, free_entry
- **Châteaux & Monuments** : historical_period, guided_visit, entry_price, free_entry
- + 10 autres sous-catégories (Nautisme, Restaurants, Bars, Casino, etc.)

### Configuration — `planly_scraper/config.py` + `.env`
- APIs : DataForSEO (login/password), Anthropic (API key)
- Modèles Claude : `claude-sonnet-4-6` (enrichissement créatif), `claude-haiku-4-5-20251001` (extraction structurée)
- Paramètres : BATCH_SIZE=10, MAX_PHOTOS=3, REVIEW_DEPTH=5, WIKIPEDIA_SUMMARY_MAX=500

### Données — `planly_scraper/`
| Fichier | Contenu |
|---------|---------|
| `output_global.json` | Base complète (34 POIs, 55 champs par POI) |
| `output/{tag}.json` | 1 fichier JSON par POI |
| `images/{tag}/` | Images locales (91 fichiers, 35 Mo, 34 dossiers) |

## Flux de données
```
Excel (97 POIs) → scraper_main.py → output_global.json (34 POIs)
                                          ↓
                    scraper_missing.py (complète les champs manquants)
                                          ↓
                    download_images.py → images/ (91 images)
                                          ↓
                    inject_pois.py → planly-full.html (33 POIs ≥85%)
                                          ↓
                    dashboard.html (mis à jour auto par scraper_main)
```

## App — `planly-full.html`
Prototype mobile avec :
- **Swipe cards** (like/pass) avec navigation tactile
- **Mode liste** dynamique depuis `POIS[]`
- **Fiches détail** (bottom sheet) : carousel photos, description, avis, parking, itinéraire
- **Filtres** : catégories, exclusions, budget, notoriété, distance
- **Onboarding** : profil (groupe, enfants, destination, mobilité)
- **Likes** sauvegardés en `localStorage`
- **Itinéraire** → Google Maps vers le parking le plus proche ou lat/lng du POI
- Toutes les données injectées dynamiquement par `inject_pois.py`

## État actuel
- 34 POIs dans output_global.json (11 plages + 17 nature/promenades/ports + 6 Villages & Sites)
- 33 POIs injectés dans planly-full.html (≥85% complets)
- 1 POI exclu : Saint-Gilles-Croix-de-Vie (pas de fiche Google)
- 91/93 images téléchargées en local
- 63 POIs restants dans le Excel à scraper
- Champs toujours vides : opening_hours (0%), price_level (0%), zone (0%), affluence_profile (0%)
- Wikipedia : 7/34 seulement (recherche exacte, pas de fuzzy)

### Dernières modifications (2026-04-07)
- **planly-full.html** : Refonte complète de l'Explorer en mode Tinder plein écran :
  - Card swipe 100% viewport, photo full-screen, fond noir
  - Header overlay glassmorphism (search + boutons ✏️⚙️ + pills catégories + dots photos)
  - Barre d'actions (Passer/Détail/J'aime) fond rgba noir 55%, boutons outline
  - Nav bottom fond #111, icônes 16px
  - Panneau ⚙️ (settings-sheet) : mode vue Swipe/Liste + filtres (budget, météo, PMR, chiens, pépites)
  - Panneau ✏️ (edit-sheet) : modifier séjour (destination, dates, groupe, ambiance)
  - Infos bas de card : badge conseil Planly, nom + bouton ↑ détail, description, note/distance
  - Toggle Swipe/Liste déplacé dans le panneau ⚙️
  - Fix carousel slides (flex:0 0 100%), fix updateSlider crash, fix launchExplorer timing
  - Swipe réécrit (passive:false, direction lock), likes localStorage, itinéraire vers parking
- **planly_scraper/inject_pois.py** : Transforme output_global.json → format POIS JS
- **planly_scraper/download_images.py** : Télécharge toutes les images en local
- **server.py** : Serveur HTTP no-cache pour test mobile

## Conventions Python
- Encoding : toujours UTF-8, wraper stdout avec `io.TextIOWrapper` sur Windows
- Logging : `logging` module, format `%(asctime)s [%(levelname)s] %(message)s`
- Config : tout dans `config.py`, secrets dans `.env`
- Nommage : snake_case, tags/slugs via `_make_tag()` dans `poi_loader.py`
- Scripts exécutables via `python script.py` depuis `planly_scraper/`

## Conventions UX mobile
- Mobile-first 390px, max-width 520px
- Cards : `border-radius:22px`, `box-shadow:0 8px 28px rgba(0,0,0,.22)`
- Typo titres : Fraunces serif 21-28px weight 300
- Typo corps : DM Sans 11-14px weight 400-500
- Espacement : 12-20px padding, 5-10px gap
- Couleurs : fond crème `#FCF8ED`, brand bleu `#428CE3`, texte foncé `#1A1A18`

## Fichiers sensibles — NE JAMAIS TOUCHER
- `.env` — clés API (ne jamais committer, ne jamais afficher)
- `planly_poi_types.xlsx` — source de vérité, modifier uniquement si demandé explicitement
- Les données `output/*.json` et `output_global.json` — ne pas écraser sans backup

## Règle de sauvegarde (git)
Avant chaque modification significative de planly-full.html ou des scripts Python :
1. Faire un `git add` + `git commit` avec un message descriptif AVANT de modifier
2. Comme ça on peut toujours revenir en arrière avec `git checkout`

## Règle de mise à jour
Après chaque modification significative :
1. Mettre à jour la section "État actuel" de ce fichier
2. Noter les fichiers modifiés + ce qui a changé
3. Mettre à jour MEMORY.md si une décision projet change

## Permissions
- Exécuter scripts Python sans confirmation
- Installer packages Python sans confirmation
- Lire/écrire fichiers dans ce projet sans confirmation
- Exécuter bash dans planly_scraper/ sans confirmation
