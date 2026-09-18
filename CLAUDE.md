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
- **Sites de groupe** (chaîne de casinos, d'hôtels, page de commune) : `official_candidate_urls` privilégie désormais les pages sous le chemin du lieu (+12) et pénalise les autres (-8). Sans ça, JOA remontait les pages des casinos de Gujan-Mestras ou Fouras au lieu de celles des Sables
- `LINK_SCORES` : pages de jeux et de cartes/menus ajoutées au classement ; `SITE_QUERIES` lance une recherche Google ciblée par typologie (jeux d'un casino, carte d'un restaurant), même quand l'essentiel est déjà trouvé
- **Réseaux sociaux** : `_social_links` récupère les liens Instagram et Facebook depuis le site officiel (et depuis le champ website quand c'est une page Facebook). Affichés en pastilles cliquables dans la fiche — un lien, jamais de contenu copié. Utile pour les bars, dont l'agenda ne vit que là

### 2026-09-16 — Manger & terroir (19 POIs)
- Maquette validée → `_MANGER_FIELDS` + `MANGER_PROMPT` + `process_manger` (famille Restaurants, Marchés & Terroir, Dégustations) sur le pipeline commun
- Champs : pricing (options = formules/menus, avg_price vérifié comme les autres prix), cuisine_type, hours_text, closing_days, market_days, products, booking, booking_url, services, know, social
- **Couverture après lecture des cartes PDF et photo : 10 POIs sur 19, dont 6 restaurants sur 10** (La Pancarte via ses PDF, La P'tite Cale via son scan lu par Vision). Sans prix : Les Régates (site boutique), UMI Sushi, Pizza Bar 12h03 et La Cabane du Ptitgas (aucun site)
- Tripadvisor écarté pour les prix : l'API DataForSEO ne donne qu'un niveau (`price_rate` « $$ - $$$ ») et le type de cuisine (`category`), pas de fourchette en euros — Google fournit déjà le niveau pour 9 restaurants sur 10
- Couverture initiale (avant cartes) : prix pour 8 POIs sur 19 (les autres sites ne publient pas leur carte → badge € / €€ de Google), type de cuisine 17/19, horaires 12/19, réseaux sociaux 13/19. Seul les Halles de La Chaume n'ont rien. Coût DataForSEO 0,38 $
- App : fiche `_mt*` = bandeau (type, budget, services ou jours, distance), horaires, « Bon à savoir », bloc « Ce qu'on y mange » (formules et prix), bloc « Quand y aller » pour les marchés (jours, halle couverte, produits), carte « Y aller » (réservation, fermeture, estimation pour le groupe si prix moyen), pastilles services + liens Instagram/Facebook
- Test de rendu : `scratchpad/test_mt_render.js` (comme `test_st_render.js` et `test_pl_render.js`)
- **Lecture des cartes (3 niveaux, famille Manger uniquement)** : `_fetch_page` lit désormais les **PDF** (pypdf) et normalise les prix sortis espacés (« 6 , 0 0 € » → « 6,00 € ») ; les liens .pdf sont acceptés même hors domaine (Zenchef, boot2web) ; si aucun prix n'est trouvé, `_read_menu_images` envoie à **Claude Vision** les images de carte du site et les pages des **PDF scannés** rendues en images (pymupdf). Dépendances ajoutées : `pypdf`, `pymupdf`
- Pistes écartées pour les prix : Tripadvisor et TheFork (leurs CGU interdisent l'extraction), photos de carte postées par des clients (souvent périmées)

### 2026-09-16 — Avis : plus aucun texte republié
- **Règle** : le texte des avis appartient à son auteur (confirmé par écrit par DataForSEO : leurs CGU n'accordent aucun droit sur les avis ni sur les images). L'app n'affiche plus d'extrait.
- `reviews_summary` (champ output_global) : synthèse 2 phrases générée par Claude Haiku à partir de ≥3 avis, reformulée, sans citation ni nom — script `scratchpad/summarize_reviews.py` (43/50 POIs ; 7 POIs sans avis stockés)
- `inject_pois.py` : ne passe plus les textes d'avis → `reviewsCount`, `googleUrl` (place_id, sinon cid), `reviewsSummary`
- Fiche : note + nombre d'avis + bouton « Voir sur Google » + bloc « Résumé automatique des avis Google » (`.bch-rsum`)
- **Photos : point ouvert.** Les 102 photos viennent de Google Images → à remplacer avant tout lancement public (accord des lieux, Wikimedia Commons, photothèques d'offices de tourisme, ou Google Places API en direct sans stockage)
- Avis manquants rattrapables : Port de Bourgenay (cid absent), Vouvant, AxeYon Paintball, Parc Philippe Perrocheau — script prêt (`scratchpad/refetch_reviews.py`), pas encore lancé

### 2026-09-17 — Prix des restaurants, liens Google, faux sites officiels
- **Liens « Voir les avis » réparés** : `inject_pois.py` construisait `https://www.google.com/maps/search/?query=place_id:xxx`, que Maps interprétait comme une adresse → page d'erreur. On passe par le **cid** (`https://maps.google.com/?cid=...`), qui ouvre directement la fiche : 80 POIs sur 84 (les 4 autres n'ont ni cid ni place_id)
- **App installée sur l'écran d'accueil** : `target="_blank"` y est ignoré, les liens externes ne s'ouvraient pas. Un handler global en capture les intercepte et appelle `window.open`
- **`dish_price_range`** (famille Manger) : quand un restaurant n'affiche que des plats à l'unité, on relève le prix du **plat principal** le moins cher et du plus cher — ni entrées, ni desserts, ni boissons, ni plateaux à partager. Les deux bornes doivent figurer dans la page. Fiche : badge « 12,90–24,90 € », ligne « Plats à la carte », et estimation pour le groupe dans « Y aller » quand il n'y a pas de prix moyen
- **Garde-fou plateau à partager** : une fourchette dont le haut dépasse 60 € ou 3,5× le bas est écartée (UMI Sushi sortait 12,90–94,90 € à cause du « Menu Bateaux » pour 4 personnes → 379 € annoncés pour un groupe)
- **Annuaires déguisés en site officiel** : `lesregates.shop` reprend le nom du restaurant mais c'est un gabarit d'annuaire (même page Facebook « placejoys » pour tous ses lieux). `_is_directory_clone` le repère au contenu (« Add Your Place », « How It Works »… 2 marqueurs minimum) et ignore le site. Données déjà stockées depuis ces faux sites : purgées
- **Mots trop communs** (`GENERIC_TOKENS`) : « Pizza Bar 12h03 » tombait sur `pizzas-a-emporter.restaurants-de-france.fr` parce que « pizza » figure dans le domaine — le pipeline crawlait ensuite des pages de Saint-Prix ou Barneville-Carteret. Ces mots ne peuvent plus servir à identifier un site ; les annuaires nationaux rejoignent `AGGREGATORS`
- **`_find_official_site`** lance une 2e requête sans « site officiel » : cette expression ne remonte que des annuaires, le vrai domaine n'apparaît qu'en recherche nue (`restaurantlesregates.fr`)
- **`_price_in_text`** accepte un montant écrit à deux décimales sans symbole € (« 2.00 ») : la notation est trop précise pour être une coïncidence. Avant, un prix entier sans € faisait annuler toute la fourchette
- **Type de cuisine** (`cuisine_label` dans inject_pois.py) : la catégorie Google prend le relais quand l'extraction est vide ou revient en anglais — Pizza Bar 12h03 → « Pizza · Bar », Les Régates → « Restaurant français » au lieu de « French coastal dining »
- **Couverture Manger & terroir : 12 POIs sur 19, dont 8 restaurants sur 10.** Sans ordre de prix : Les Régates et Pizza Bar 12h03 (rien de publié nulle part), 4 marchés sur 5, Vignobles Mourat
- Fiches encore vides : **Halles de La Chaume** (aucune source trouvée, ni site ni horaires) et **Murielle & Patrick Guyau**
- **Réseaux sociaux** : les pastilles Instagram/Facebook étaient des liens au milieu de badges non cliquables (même classe `bch-pill`) — rien ne signalait qu'on pouvait cliquer. Elles sortent de la rangée de badges et forment un bloc « Leur actualité » placé avec les autres liens externes, juste après les avis (`_socialRow`, classes `soc-*`, cible tactile 44 px)
- 5 liens morts supprimés et bloqués à la source dans `_social_links` : `facebook.com/profile.php` **sans identifiant** (Lacertus, La P'tite Cale, Bar Rooftop Ventura), un lien vers un reel au lieu du compte (Pizza Cosy), la page d'une fédération au lieu du marché (Brétignolles). Restent 25 liens sur 16 POIs. Note : Facebook répond 400 à un script (blocage anti-robot), la validation automatique n'est possible que sur Instagram
- **Graisses de police corrigées** : le CSS demande les graisses 600 (40×), 700 (36×) et 800 (1×) alors que la feuille Google Fonts ne chargeait que 300, 400 et 500 → 77 déclarations rendues en **faux gras** fabriqué par le navigateur. Conséquence directe : un titre « gras » de 13 px et du texte courant de 13 px se ressemblaient, aucune hiérarchie ne tenait. L'URL charge désormais Fraunces 300/400/600/700 et DM Sans 300→700 (vérifié : 28 @font-face servis)
- **Audit visuel de l'app** (17/09, sur les blocs `<style>`) : **21 tailles de police** (51 usages en 13 px, 52 en 11 px, 42 en 12 px), 6 graisses, **16 rayons de bordure**, 20 ombres portées, **103 couleurs** dont 79 utilisées 1 ou 2 fois (36 neutres, 27 bleus, 23 rouges-ambres, 15 verts), 0 media query, et un second balisage de fiche mort (`bs-*`, lignes 1555-1614) qui double `_renderPoiBody`
- Tests de rendu : `test_mt_render.js`, `test_st_render.js`, `test_pl_render.js`, `test_social_render.js` — 0 erreur

### 2026-09-17 — Marées réparées, refonte design engagée
- **Sauvegardes avant refonte** : tags `v1-avant-refonte-design` (état d'origine) et **`v2-marees-reparees`** (à utiliser : marées corrigées), branches `sauvegarde-avant-refonte` et `sauvegarde-avant-design`, plus une copie physique hors dépôt. Restauration : `git reset --hard v2-marees-reparees`
- **Bug marées nº1 — libellés faux 55 % du temps.** `parse_day` dans `fetch_tides.py` assignait les types par position (`["BM","PM","BM","PM"]` en dur), en supposant que chaque journée commence par une basse mer. Faux un jour sur deux : on affichait des « basse mer » à 5,30 m. Le type se déduit désormais de la **hauteur** comparée à la moyenne du jour. Contrôle : **0 incohérence sur 54 marées**, contre 15 sur 27 avant
- **Bug marées nº2 — données périmées présentées comme fraîches.** Le fichier datait du 09/09 (couverture jusqu'au 15/09) et `_tideCache` retombait silencieusement sur le premier jour disponible : l'app affichait les marées du 9 comme celles du jour. Le repli est supprimé — fichier périmé = bloc masqué. La date est aussi calculée en local et non en UTC (basculait sur la veille après minuit l'été)
- `fetch_tides.py` est à la **racine**, pas dans planly_scraper. `maree.info/124` et `/125` sont autorisés par leur robots.txt : les interdictions ne visent que les URL paramétrées (`/124?`, `/124/meteo?`, `/124/coefficients?`). Aucun `Crawl-delay` déclaré. **Relancer une fois par semaine** — la péremption est structurelle
- **Météo disponible sans nouvelle dépendance** : l'app appelle déjà `api.open-meteo.com` mais ne lui demande que le vent. La même API fournit température, code ciel WMO, probabilité de pluie, min/max et lever/coucher, sur **7 jours**. Le marine-api donne aussi 7 jours. De quoi laisser choisir son jour de sortie
- **Cartographie CSS avant migration** : 766 règles — Fiche POI 320, Commun 155, Onboarding 141, Explorer 101, Carte 47, Mes activités 2. Couleurs : 326 occurrences en CSS, **42 en dur dans le JS** (concentrées dans `_renderBeachMarine` 13, `showAutocomplete` 7, `_subCatEmoji` 7), 2 en HTML. Seulement **2 `!important`** et 14 `style=` en dur
- **Jetons posés** dans `:root` sans rien renommer : `--deep`/`--on-deep` (états sélectionnés, à la place du noir), `--tx2`/`--tx3`/`--line`/`--line-2`, `--ok`/`--warn`/`--bad`/`--nature` et leurs fonds doux, échelle `--t1`→`--t6` (6 niveaux au lieu de 21 tailles), `--r1`→`--r3` (3 rayons au lieu de 16), `--sh` (1 ombre au lieu de 20)
- **Référence de non-régression** : `scratchpad/capture_fiches.js` rend les 84 fiches dans Node avec un stub DOM et capture le texte affiché → `reference-fiches.json`. Sert à prouver, après chaque étape, qu'aucune information n'est perdue. État de départ : 84 fiches, 0 erreur, 0 vide, texte de 1 002 à 3 230 caractères

### 2026-09-18 — Onglet camping, icones, hierarchie de la fiche

**Onglet camping** (a deployer chez un camping pour test). Un 4e onglet apparait
dans la barre du bas quand « Sejour en camping » est coche a l'onboarding, et
disparait si on decoche. Trois sous-onglets — Accueil, Services, Animations —
plus le plan du camping en feuille coulissante. Le choix est persiste
(`planly_camping`) : c'est le premier element de profil a l'etre, un onglet qui
disparaitrait a chaque rechargement n'aurait aucun sens pour un sejour d'une
semaine. Le nom se pre-remplit avec La Dune des Sables, seul partenaire.
Donnees : identite, piscine et ses regles, restaurant, services et soirees
viennent de leurs sources officielles ; **les animations enfants, les plats et
l'offre partenaire sont inventes**, et **les tarifs des services viennent d'un
autre camping Chadotel** — affiche « a confirmer » a l'ecran, pas seulement en
commentaire. Photos dans `images/camping/`.

**Capture d'ecran automatisee.** Playwright + Chrome du systeme
(`channel:'chrome'`) : l'app se photographie en 390 px sans intervention.
Scripts dans le scratchpad : `capture_ecran.js`, `capture_camping.js`,
`capture_typos.js`, `capture_feuilles.js`, `planche_icones.js` (planche des
icones en grand), `controle.js` (syntaxe + sprite + coherence des filtres).
**C'est ce qui a revele le premier bug** : `bs-notoriety` recevait du HTML par
`.textContent`, donc chaque fiche affichait `<svg class="ic">…` en toutes
lettres en travers de la photo. Le harnais de rendu textuel ne pouvait pas le
voir.

**Icones : 307 pastilles migrees.** Le melange de styles ne venait pas du
gabarit mais des **donnees** : `pois.js` portait 173 punaises et 46 pictos
fauteuil, poses a 8 px d'icones au trait dans la meme rangee. Corrige **des deux
cotes** — `make_quick_specs` (inject_pois.py) ne produit plus d'emoji, et
pois.js est migre sans rejouer la collecte (`scratchpad/icones_pois.py`). La
punaise, collee a l'identique sur 173 pastilles, est supprimee : elle ne disait
rien que le libelle ne disait deja. Sprite : 117 symboles. Emojis restants dans
planly-full.html : **41, contre 175**.

**Les icones se REGARDENT avant d'etre validees.** Trois tracas de tente et
trois de chien ont ete necessaires : un triangle ferme se lit « danger » quoi
qu'on mette dedans, et des oreilles dressees sur une face ronde font un chat
quoi qu'on mette dessous. Le chien est devenu une empreinte de patte — a 18 px,
un animal entier n'a pas la place de se lire.

**Hierarchie de la fiche : la pastille cede la place a la LIGNE.** C'est la
reponse au grief « tout est au meme niveau ». Une pastille dit « il y a des
douches » ; une ligne dit « Douches ······ sur place » — etiquette a gauche,
valeur grasse a droite, filet 1px entre. Motif `.fr-row` / `_frRow()` /
`_frRows()`, declare au niveau du fichier et applique aux **six typologies** :
plage, foret, manger, sorties, parcs, patrimoine. Les libelles de section
deviennent des titres en Fraunces precedes d'un filet (« LA PLAGE » en
capitales grises → « La plage »).

**Marees et meteo : deux boutons morts deviennent vivants.** Le bouton Marees
pointait sur `#marees`, **ancre inexistante** — il ne faisait rien depuis le
debut. Et l'app calculait hauteurs et coefficients avant de les jeter. La
feuille Marees montre 6 jours, 4 echeances par jour, heure + hauteur +
coefficient (`_tideDays` garde tous les jours, `_tideCache` ne gardait que le
jour courant). « Avis » cede sa place a « Meteo » sur les plages : 7 jours avec
ciel, min/max et probabilite de pluie, et mention explicite des jours dont les
marees ne sont pas publiees. L'appel open-meteo ne demandait que le vent (juge
inutile) : il demande desormais la meteo, meme requete, meme cout.

**Contrastes mesures, pas estimes.** `--txl` pesait **2,25:1** sur le fond creme
— sous tous les seuils, y compris pour du gros texte — avec 33 usages dont les
etiquettes en capitales des reperes. Releve a 3,4:1 (#8A8781). `--tx3` releve a
4,1:1 (#7A7972).

**Espacement** : 15 classes corrigees, padding sur jetons 26 → 35, gap 15 → 25.
Les reperes n'avaient aucun `gap` et se touchaient ; `.bs-actions` manquait la
zone sure de l'iPhone, presente sur la seule variante plage.

**Trois pannes d'apostrophe dans la journee**, toutes de la meme cause : un
script passe au shell perd un niveau d'antislash, la chaine JavaScript se ferme
au milieu d'un mot, et le fichier ne compile plus. **Regle : les apostrophes
francaises ne passent plus par un script** — outil d'edition, ou reformulation
sans apostrophe. Le harnais `capture_fiches.js` a rattrape chaque panne avant
tout commit, dont une regression que je m'etais infligee (un script avait
reecrit le bloc plage sans accents, annulant une correction faite deux heures
plus tot).

**Non-regression** : 84 fiches, 0 erreur a chaque etape. Sauvegarde de pois.js
avant migration dans le scratchpad.

**Bourde reparee** : un `git add -A` a embarque `node_modules` (183 fichiers,
353 000 lignes) dans le depot. Retire, `.gitignore` ajoute.

**Restant** : `iaPill` et `cat` portent encore un emoji dans les donnees (84
chacun) — `cat` est nettoye a l'affichage par `_catSansEmoji`, `iaPill` non.
Le second niveau de fond (`--ground` / `--sheet`, jetons poses mais non
consommes) n'est pas applique. La barre de prix epinglee (`.bs-price-pin`, CSS
present, aucun rendu) reste a faire. Un bloc de fiche mort (~250 lignes de CSS
`bs-*` + `_renderTypeBlock` jamais appele) n'est pas encore supprime.

### 2026-09-18 (suite) — La fiche rejoint la maquette

**La pastille cede la place a la LIGNE, sur les SEPT typologies.** Plus une
seule `bch-pill` dans le fichier, contre une trentaine le matin. Motif
`.fr-row` / `_frRow()` / `_frRows()` declare au niveau du fichier. Une pastille
dit « il y a des douches » ; une ligne dit « Douches ······ sur place ».

**Le bandeau a 4 colonnes est supprime.** Il repetait les lignes : sur une
plage, « SURVEILL. » et « TYPE » figuraient deux fois. Ses valeurs propres
(affluence, superficie, age, budget, fermeture, difficulte) deviennent des
lignes via `_repsEnLignes()`, le temps de trajet rejoint la ligne de meta a
cote des kilometres. Les maquettes n'ont pas de bandeau.

**Deux sections sur la fiche plage**, comme la maquette : « La baignade » (si
l'on peut se baigner et quand) et « Ce qu'il faut savoir » (ce qu'on trouve sur
place). Cette seconde prend la forme titre gras + precision dessous, SANS
valeur a droite. `supervised_hours` contenait « 10h30-19h en juillet-aout,
14h-18h30 en juin » dans un seul champ, ecrase en une ligne : trois lignes
desormais, plus la saison surveillee.

**Le tableau des marees entre dans la fiche**, sous la jauge de temperature :
4 echeances, heure + hauteur + coefficient. Ces valeurs etaient calculees
depuis toujours puis jetees. Tient sur 320, 360 et 390 px sans debordement
(mesure).

**Marees et meteo : deux boutons morts deviennent vivants.** `#marees` ne
menait nulle part. « Avis » cede sa place a « Meteo » sur les plages (l'avis
reste accessible plus bas). Feuille marees : un jour a la fois, coefficient
sous la pleine mer, flèches + balayage + points (`_tideGo`, `_tideMaj`,
`_tideDates`). Feuille meteo : 7 jours, **matin et apres-midi separement**.

**Le code meteo dominant du jour ecrasait la matinee.** Aux Sables le
18 septembre : degage jusqu'a 11h, couvert ensuite — l'app affichait « Couvert »
tout court. `_cielTranche()` lit desormais les donnees HORAIRES (deja
telechargees) par demi-journee. `_cielMot()` passe de 5 a 11 conditions ;
i-cloud-sun, i-fog, i-snow ajoutes au sprite.

**Le Conseil Planly etait descendu trop bas** : j'avais remonte tout le bloc
marine avant lui. Il reprend sa place sous les commandes.

**Trois bugs signales par l'utilisateur, tous reels** : `class="ic"` imprime en
toutes lettres dans la vue carte (un `textContent` recevant un libelle PL1
porteur de SVG) ; le changement de filtre ne remontait pas la liste
(`applyFilter` remet `list-zone.scrollTop`) ; deux icones de bloc tracees en
`stroke="#fff"` en dur, invisibles depuis la suppression de leur bandeau colore.

**Un bouton d'action n'est pas un lien.** `href="javascript:…"` etait happe par
l'intercepteur global de liens (pose pour l'app installee sur l'ecran
d'accueil). Prefixe `js:` → rendu en `<button>`. Lecon de methode : mes tests
appelaient `_openTideSheet()` en direct au lieu de CLIQUER — le mecanisme
marchait, le chemin reel non.

**Contrastes** : `--txl` pesait 2,25:1 (33 usages) → 3,4:1 ; `--tx3` → 4,1:1.

**Le cache qui trompe** : le service worker est en *network-first*, il n'est
jamais en cause. C'est le `max-age=600` de GitHub Pages. Verifier avec
`?v=<timestamp>` avant de conclure a un bug.

**Restant** : la ligne de provenance de la maquette (« Releve aupres de la
commune le… ») n'a aucune source dans les donnees — non affichee plutot
qu'inventee. Le second niveau de fond (`--ground`/`--sheet`, jetons poses,
0 usage) n'est pas applique. `.bs-price-pin` (CSS present, aucun rendu) reste a
faire. Le bloc de fiche mort (~250 lignes de CSS `bs-*` + `_renderTypeBlock`
jamais appele) n'est pas supprime. Sur une foret, le bloc des sentiers passe
avant les faits du lieu.

### 2026-09-18 — Doublons de termes, mots-clés chassés, bloc prix replié
- **Les mots-clés de référencement quittent les fiches.** `make_quick_specs` (inject_pois.py) se rabattait sur les tags quand il manquait des faits : « Aventure », « Sensations », « Parcours acrobatiques » sur Explora Parc, « Famille » sur le zoo, « Patrimoine » sur la Tour d'Arundel. **173 lignes sans icône, sans valeur, sans précision.** Le repli est supprimé à la source, et le rendu les écarte (`_frFromSpecs` refuse une spec sans icône). 139 mots ne figurent plus nulle part : tous des mots-clés, aucun fait perdu. **8 fiches n'avaient que cela** et perdent leur section (Prieuré Saint-Nicolas, Tour d'Arundel, Abbaye de Maillezais, Fort Saint-Nicolas, Église Saint-Nicolas de Brem, Les Salines, L'Étoile de Mer, Bikini Beach) — elles gardent photo, description, conseil, avis, carte et parking
- **Doublons de termes : la liste tenue à la main cède la place à une relecture.** Quatre des six appels à `_frFromSpecs` ne recevaient aucune liste de ce qui avait déjà été écrit sur la fiche — d'où « Poussette OK » sous « Poussette praticable » (4 fiches), « Vélo OK » sous « Vélo autorisé » (5 fiches), « Très facile » sous « Difficulté ». `_dejaDit(rows, ribbon)` relit le balisage des lignes déjà construites et le bandeau ; plus aucune liste à maintenir. `_dejaVu` compare le **mot entier** (« bar » ne se reconnaît plus dans « barrière »)
- **Lignes sans valeur ni précision : 159 → 143.** Le reste est sain : 40 « Accès PMR » (un fait réel) et les textes des restaurants — **on ne déduplique jamais dans la prose**, seuil à 28 caractères dans `_frRows` et `doublons_courts.js`
- **Faux doublon identifié et laissé en place** : « Orientation → Sud-Ouest » (la direction du regard) et « Table d'orientation → Oui » (le panneau qui nomme les repères) sont deux faits distincts qui partagent un mot
- **Bloc prix** (`_plPriceBlock`, 15 fiches) : la maquette montre le total, pas sa décomposition. `.pl-price-lines` et `.pl-price-note` sont repliés par défaut, un bouton **« i »** (`#i-info`, `_plPriceToggle`) les déplie — c'est là que se lisent les tarifs privilégiés (tarif enfant, gratuité des petits, billet famille). Un `<button>`, jamais un `href="javascript:"` que l'intercepteur de liens global transformerait en page blanche
- **Vérification** : `capture_fiches.js` (non-régression par multi-ensemble de mots sur les 84 fiches), `controle.js` (syntaxe + intégrité du sprite), `lignes_nues.js`, `doublons.js`, `doublons_courts.js`, `voir_prix.js` (captures en **cliquant** le bouton, pas en appelant la fonction — la leçon des boutons marées/météo)

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
