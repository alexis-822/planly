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
4. **DataForSEO images** — ~10 candidats via SERP Images, puis tri Claude Haiku Vision (`enrich_images.process_poi` : rejet flou/cartes, garde les 3 meilleures, télécharge dans `images/{tag}/`)
5. **Parkings** (`parking.py`) — Overpass API (OSM), rayon 500m/1000m
6. **Wikipedia** (`wikipedia_client.py`) — Résumé FR (500 chars max)
7. **Claude enrichissement** (`claude_enricher.py`) — Sonnet 4.6 : descriptions, tags, audience, durée, accessibilité, conseil_planly, notoriété
8. **Fusion** (`merger.py`) — Assemble toutes les sources → JSON final par POI

Le script supporte `--subcategory` (filtre). Par défaut il ignore **tout POI déjà présent** dans output_global.json (même partial, match par tag ou par nom) — on ne retouche pas les POIs existants. `--no-resume` refait tout.

### Scripts complémentaires — `planly_scraper/`
| Script | Rôle |
|--------|------|
| `scraper_missing.py` | Remplissage champs manquants (SERP organic + Claude Haiku extraction) |
| `enrich_images.py` | Tri photos Claude Vision (déjà intégré à scraper_main pour les nouveaux POIs ; en manuel : `--poi tag1,tag2`, jamais sans `--poi`) |
| `download_images.py` | Ancien téléchargement sans tri Vision — ne plus utiliser |
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
       (photos triées par Claude Vision directement dans scraper_main)
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
### 2026-09-14 — Parcs & Loisirs
- **50 POIs** : les 34 historiques (non retouchés) + **16 Parcs & Loisirs** (11 Jeux & Divertissement, 2 Parcs animaliers, 1 Aquarium, 2 Parcs botaniques), tous injectés dans l'app
- Coût DataForSEO des 16 : 0,056 $ (+ quelques centimes pour la relance photos)
- Photos : tri Claude Vision intégré à scraper_main ; les photos de fiches Google (lh3 gps-cs-s) renvoient 403 en téléchargement direct → seules les photos SERP Images sont utilisables
- `scraper_missing.py` exige `--subcategory` ou `--poi`. Parcs & Loisirs (`process_parcs_loisirs`) itère : site officiel (pages classées par pertinence via liens + sitemap, robots.txt respecté) → Google `site:domaine` (DataForSEO) → office de tourisme / commune. Prix acceptés seulement s'ils figurent tels quels dans la page source (`_price_in_text`), tarifs d'une année passée marqués `stale`. Formes gérées : adulte/enfant + tranches d'âge, billet famille, entrée gratuite, « à partir de », forfaits. Champs : pricing, activities, shows, hours_text, season, booking, indoor_outdoor, amenities, official_source
- **Couverture des 16** : prix 16/16 (Ânes Passions = tarifs 2025, site non mis à jour), horaires 16/16 (10 Google, 5 site officiel, Vague de Jeux « sur réservation »)
- Bug corrigé : `dataforseo.py` lisait `work_time.timetable` au lieu de `work_time.work_hours.timetable` → opening_hours était vide pour tous les POIs (les 34 historiques n'ont pas été re-scrapés)
- `truststore` installé (certificats Windows, ex. vendee-tourisme.com)
- App : pill Parcs & Loisirs filtre les 4 sous-catégories (catégories `jeux`, `animaux`, `aquarium`, `jardin`). Fiche Parcs & Loisirs = maquette validée intégrée (`_pl*` dans planly-full.html) : ouvert aujourd'hui + semaine (timetable Google `openingHours`), prix pour le groupe (profil onboarding, 2 adultes par défaut pour famille/amis), activités avec pastilles âge enfants, animations, pastilles équipements, alerte conseil automatique, source + date de vérification des tarifs
- Coûts mesurés : DataForSEO ≈ 0,016 $/POI (collecte) ; passes site officiel ≈ 0,26 $ au total pour 16 POIs

### 2026-09-16 — 88 POIs, Sorties & Détente traitée
- **88 POIs** en base, **84 injectés** (4 sous le seuil 85 % : Murielle & Patrick Guyau, Domaine Saint Nicolas, Les Voiles de Cayola, Côte Ouest Thalasso)
- Nouveaux : 19 Art de vivre (10 restaurants, 5 marchés, 4 dégustations), 9 Patrimoine (5 monuments, 4 musées), 10 Sorties & Détente (4 bars, 2 casinos, 2 cinémas, 2 piscines/spa). Coût DataForSEO ≈ 0,22 $
- **Sorties & Détente** : maquette validée (https://claude.ai/code/artifact/55c28103-ce83-4664-b26a-90acd14b470e) → `_SORTIES_FIELDS` + `SORTIES_PROMPT` + `process_sorties` dans scraper_missing ; champs pricing, hours_text, closing_time, age_min, booking, know (3 points « bon à savoir »), facilities, services
- `_run_official_pipeline` : pipeline commun (site officiel → Google `site:domaine` → office de tourisme) partagé par Parcs & Loisirs et Sorties & Détente. Nouveau : `_find_official_site` cherche le site quand Google ne le donne pas (un mot du nom doit figurer dans le domaine)
- **Règle** : « entrée libre » ne vaut pas « sortie gratuite » pour un bar ou un restaurant (pricing ignoré) ; pour un casino la fiche affiche « Entrée libre, les jeux sont payants » ; pour un bar seuls les prix de boissons sont retenus
- App : fiche Sorties (`_st*`) = bandeau par typologie, horaires, « Bon à savoir », budget (tarifs si publiés, sinon niveau Google, sinon « non communiqués »), bloc jeux/installations, carte séances pour le cinéma, avertissement âge minimum si des enfants voyagent
- Pills : Art de vivre, Patrimoine et Sorties & Détente filtrent enfin leurs lieux (`resto`, `marche`, `degustation`, `bar`, `casino`, `cinema`, `spa`, `culture`)
- **Restant : 9 POIs** (5 Nautisme, 4 Autres sports) + extraction site officiel pour Art de vivre et Patrimoine, pas encore faite
- `_find_official_site` a rattrapé Les Voiles de Cayola et la thalasso Côte Ouest (horaires + installations). Restent sans aucune source : L'Étoile de Mer (Facebook seulement) et Bikini Beach
- **Badge budget corrigé** (`make_budget`) : il utilise le `price_level` de Google (inexpensive → €, moderate → €€) ; « Gratuit » est réservé aux lieux réellement gratuits — un restaurant, un bar, un casino ou un cinéma sans tarif connu affiche « Prix non communiqué », jamais « Gratuit »
- Casinos : les chiffres utiles au joueur sont demandés explicitement (nb de machines, de tables, jeux électroniques). Casino des Sables → 75 machines, Boule 2000, Black Jack 7 postes ; JOA ne publie pas ses quantités
- Photos : un `search_keyword` par POI permet de rattraper une recherche d'images infructueuse (fait pour Aqualonne)
- Maquette « Manger & terroir » (restaurants, marchés, dégustations) : https://claude.ai/code/artifact/bba72057-c5d2-462f-b655-a1df465b2e30 — à valider avant extraction et fiche

### 2026-09-16 — Avis : plus aucun texte republié
- **Règle** : le texte des avis appartient à son auteur (confirmé par écrit par DataForSEO : leurs CGU n'accordent aucun droit sur les avis ni sur les images). L'app n'affiche plus d'extrait.
- `reviews_summary` (champ output_global) : synthèse 2 phrases générée par Claude Haiku à partir de ≥3 avis, reformulée, sans citation ni nom — script `scratchpad/summarize_reviews.py` (43/50 POIs ; 7 POIs sans avis stockés)
- `inject_pois.py` : ne passe plus les textes d'avis → `reviewsCount`, `googleUrl` (place_id, sinon cid), `reviewsSummary`
- Fiche : note + nombre d'avis + bouton « Voir sur Google » + bloc « Résumé automatique des avis Google » (`.bch-rsum`)
- **Photos : point ouvert.** Les 102 photos viennent de Google Images → à remplacer avant tout lancement public (accord des lieux, Wikimedia Commons, photothèques d'offices de tourisme, ou Google Places API en direct sans stockage)
- Avis manquants rattrapables : Port de Bourgenay (cid absent), Vouvant, AxeYon Paintball, Parc Philippe Perrocheau — script prêt (`scratchpad/refetch_reviews.py`), pas encore lancé

### Avant (historique)
- 34 POIs dans output_global.json (11 plages + 17 nature/promenades/ports + 6 Villages & Sites)
- 33 POIs injectés dans planly-full.html (≥85% complets)
- 1 POI exclu : Saint-Gilles-Croix-de-Vie (pas de fiche Google)
- 91/93 images téléchargées en local
- 63 POIs restants dans le Excel à scraper
- Champs toujours vides : opening_hours (0%), price_level (0%), zone (0%), affluence_profile (0%)
- Wikipedia : 7/34 seulement (recherche exacte, pas de fuzzy)

### Dernières modifications (2026-04-11)
- **planly-full.html** :
  - **Points de vue** : CSS `pdv-*` (bloc bleu #185FA5) + fiche enrichie :
    - Ribbon : altitude (m) / meilleur moment / accès / distance
    - Bloc bleu : header avec `view_description`, badge orientation/panoramique, 3 colonnes (orientation / idéal / météo), footer tempête si `storm_interest=true`, pills (table orientation, nb marches, PMR)
  - **Forêts & Nature** : CSS `frt-*` (bloc vert #2d5a1b) + fiche parcours :
    - Header vert avec nb parcours, onglets Rando / Vélo
    - Parcours numérotés, dots difficulté CSS, bouton "Voir →" vers AllTrails/Komoot/Decathlon
    - Tri par distance croissante (null en dernier), max 5 par onglet
    - margin-top 16px sur conseil Planly après le bloc trails
  - **UX** : bouton "Ajouter à mes activités" → ferme la fiche + swipe like + passe à la card suivante (délai 320ms)
- **scraper_missing.py** :
  - `process_forets_nature()` : SERP `site:alltrails.com/fr/randonnee` + Komoot + Decathlon, 2-pass completion, validation URL par unicodedata, dedup, tri distance
  - `process_points_de_vue()` : 7 nouveaux champs (altitude_m, orientation, view_description, storm_interest, has_orientation_panel, nb_steps, ideal_weather), 2 blocs (Haiku corpus + SERP altitude)
  - Règles d'inférence explicites : coucher de soleil/vue Atlantique → O, tempête → storm_interest, etc.
- **planly_scraper/_fix_pdv_missing.py** : second pass inférence Points de vue (champs encore null)
- **planly_scraper/_run_points_vue.py** : runner batch Points de vue
- **dashboard.html** : SPECIFIC_FIELDS mis à jour pour Forêts & Nature (trails) + Points de vue (7 champs)

### Modifications antérieures (2026-04-07)
- **planly-full.html** : Refonte complète de l'Explorer en mode Tinder plein écran :
  - Card swipe 100% viewport, photo full-screen, fond noir
  - Header overlay glassmorphism (search + boutons ✏️⚙️ + pills catégories + dots photos)
  - Barre d'actions (Passer/Détail/J'aime) fond rgba noir 55%, boutons outline
  - Nav bottom fond #111, icônes 16px
  - Panneau ⚙️ (settings-sheet) : mode vue Swipe/Liste + filtres (budget, météo, PMR, chiens, pépites)
  - Panneau ✏️ (edit-sheet) : modifier séjour (destination, dates, groupe, ambiance)
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
