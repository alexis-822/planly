"""
Complète output_global.json avec TOUS les champs du schéma BDD.
- Ajoute les champs manquants en null (ne touche pas aux valeurs existantes)
- Ajoute un champ _labels avec la description FR de chaque champ anglais
- Met à jour le dashboard
"""
import io, json, os, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(__file__)
JSON_PATH = os.path.join(SCRIPT_DIR, "output_global.json")
DASHBOARD_PATH = os.path.join(SCRIPT_DIR, "..", "dashboard.html")

# ─────────────────────────────────────────────
# SOCLE COMMUN — champs + description FR
# ─────────────────────────────────────────────
SOCLE_FIELDS = {
    "id": "Identifiant unique (slug)",
    "name": "Nom du lieu",
    "name_google": "Nom tel qu'affiché sur Google",
    "category": "Catégorie principale (ex: Nature & Grand Air)",
    "subcategory": "Sous-catégorie (ex: Plages & Côte)",
    "commune": "Commune du lieu",
    "zone": "Zone géographique : nord · centre · sud",
    "poi_format": "Format : poi (lieu précis) ou destination (zone à explorer)",
    "lat": "Latitude GPS",
    "lng": "Longitude GPS",
    "address": "Adresse postale complète",
    "phone": "Numéro de téléphone",
    "website": "Site web officiel",
    "rating": "Note Google (ex: 4.7)",
    "reviews_count": "Nombre d'avis Google",
    "rating_distribution": "Répartition des notes (1 à 5 étoiles)",
    "affluence_profile": "Niveau d'affluence : calme · animé · très fréquenté",
    "popular_times": "Affluence heure par heure par jour de la semaine",
    "photos": "URLs des photos",
    "opening_hours": "Horaires d'ouverture par jour",
    "booking_url": "URL de réservation",
    "reviews": "Avis Google (texte, note, date)",
    "place_topics": "Sujets fréquents dans les avis",
    "cid": "Identifiant Google CID",
    "place_id": "Identifiant Google Place",
    "wikipedia_description": "Résumé Wikipedia FR",
    "description_short": "Accroche courte (2 lignes, pour la card swipe)",
    "description_long": "Description complète (80-120 mots, page détail)",
    "tags": "Mots-clés contextuels (ex: randonnée, plage, famille)",
    "conseil_planly": "Conseil personnalisé selon le profil utilisateur",
    "audience": "Publics cibles : famille · couple · solo · ados",
    "age_min": "Âge minimum recommandé",
    "weather_ok": "Météo compatible : sunny · cloudy · rainy",
    "duration_min": "Durée estimée en minutes",
    "accessibility": "Accessibilité (fauteuil, marche difficile, poussette)",
    "dogs_allowed": "Animaux acceptés",
    "notoriety": "Notoriété : incontournable · pepite",
    "price_range": "Gamme de prix : gratuit · eco · equilibre · plaisir",
    "price_adult": "Prix adulte en €",
    "price_child": "Prix enfant en €",
    "is_indoor": "Activité en intérieur",
    "has_height": "Implique hauteur/vertige",
    "animals_captive": "Animaux en captivité",
    "seating_available": "Bancs, tables, espace assis disponible",
    "rainy_day_activity": "Activité possible par temps de pluie",
    "parking_main": "Parking principal le plus proche",
    "parking_others": "Autres parkings à proximité",
    "scraped_at": "Date du scraping",
    "enriched_at": "Date de l'enrichissement IA",
    "status": "Statut : complete · partial · empty",
}

# ─────────────────────────────────────────────
# CHAMPS SPÉCIFIQUES par sous-catégorie
# ─────────────────────────────────────────────
SPECIFIC_FIELDS = {
    "Plages & Côte": {
        "beach_type": "Type de plage : sable · galets · rochers · mixte",
        "water_activity": "Activités nautiques : baignade · surf · paddle · kayak",
        "supervised": "Plage surveillée (oui/non)",
        "supervised_start": "Date début surveillance (ex: 01-07)",
        "supervised_end": "Date fin surveillance (ex: 31-08)",
        "supervised_hours": "Horaires surveillance (ex: 10h-19h)",
        "showers": "Douches disponibles sur la plage",
        "tide_sensitive": "Dépend des marées",
        "wave_profile": "Profil des vagues : calme · modéré · fort",
        "dogs_allowed_beach": "Chiens autorisés sur la plage",
        "naturist": "Plage naturiste",
        "beach_bar": "Bar ou buvette sur place",
        "facilities_kids_club": "Club enfants",
        "facilities_playground": "Jeux enfants fixes",
        "facilities_beach_games": "Pétanque, volley, ping-pong...",
        "facilities_sun_loungers": "Transats/parasols à louer",
        "facilities_beach_shop": "Location matériel nautique",
    },
    "Forêts & Nature": {
        "terrain_type": "Type de terrain : forêt · marais · lac · dune · bocage · île · réserve",
        "surface_ha": "Superficie en hectares",
        "difficulty": "Difficulté du parcours : facile · modéré · difficile",
        "stroller_ok": "Accessible en poussette",
        "bike_allowed": "Vélo autorisé",
        "wildlife_observation": "Observation faune/flore notable",
        "wildlife_description": "Espèces observables (ex: hérons, aigrettes, avocettes)",
        "guided_tour": "Visite guidée disponible",
        "guided_tour_info": "Horaires, prix, contact visite guidée",
        "free_access": "Accès libre et gratuit",
        "shade_level": "Niveau d'ombre : ombragé · semi-ombragé · exposé",
        "picnic_area": "Aires pique-nique disponibles",
        "trails": "Sentiers : [{nom, km, difficulté, dénivelé, lien_gpx}]",
        "trail_link": "URL Komoot/AllTrails",
        "tide_sensitive": "Accès dépendant des marées",
        "ferry_pricing": "Tarifs ferry (spécifique Île d'Yeu)",
    },
    "Points de vue": {
        "view_type": "Type de vue : mer · campagne · ville · coucher_soleil · port",
        "terrain_type": "Type de terrain : plat · falaise · colline · rocheux",
        "altitude_m": "Hauteur en mètres si notable",
        "access_type": "Accès : pied · voiture · vélo · tous",
        "walk_distance_m": "Distance à pied depuis le parking (m)",
        "difficulty": "Difficulté d'accès : facile · modéré · difficile",
        "best_time": "Meilleur moment : lever · journée · coucher · nuit",
        "panoramic": "Vue panoramique (oui/non)",
        "tripod_useful": "Trépied utile pour photographes",
        "tide_sensitive": "Accès dépendant des marées",
    },
    "Balades & Promenades": {
        "distance_km": "Distance totale en km",
        "elevation_m": "Dénivelé en mètres",
        "difficulty": "Difficulté : facile · modéré · difficile",
        "loop": "Parcours en boucle (oui/non)",
        "surface_type": "Surface : bitume · chemin · sable · mixte",
        "stroller_ok": "Accessible en poussette",
        "bike_allowed": "Vélo autorisé",
        "shade_level": "Ombre : ombragé · semi-ombragé · exposé",
        "viewpoints_count": "Nombre de points de vue sur le parcours",
        "start_point": "Lieu de départ",
        "end_point": "Lieu d'arrivée si aller simple",
        "parking_start": "Parking disponible au départ",
        "refreshment_stop": "Bar ou buvette sur le parcours",
        "trail_link": "URL Komoot/AllTrails",
        "best_time": "Meilleur moment pour la balade",
        "tide_sensitive": "Dépend des marées",
    },
    "Restaurants": {
        "cuisine_type": "Types de cuisine : fruits_de_mer · crêperie · brasserie · gastronomique...",
        "price_range_detail": "Fourchette de prix (ex: 25-40€/pers hors boissons)",
        "reservation_required": "Réservation obligatoire",
        "reservation_url": "URL réservation (TheFork, site direct)",
        "walk_in_possible": "Accepte sans réservation",
        "terrace": "Terrasse disponible",
        "terrace_view": "Vue depuis la terrasse : mer · port · jardin",
        "kids_menu": "Menu enfant disponible",
        "high_chair": "Chaises hautes disponibles",
        "dogs_welcome": "Chiens acceptés en terrasse",
        "local_products": "Produits locaux / vendéens mis en avant",
        "vegetarian_options": "Options végétariennes",
        "gluten_free_options": "Options sans gluten",
        "open_sunday": "Ouvert le dimanche",
        "open_lunch": "Service du midi",
        "open_dinner": "Service du soir",
        "live_music": "Musique live régulière",
        "seasonal_only": "Ouvert uniquement en saison",
        "best_dish": "Plat signature le plus mentionné dans les avis",
        "ambiance": "Ambiance : décontracté · familial · romantique · festif · gastronomique",
    },
    "Marchés & Terroir": {
        "market_type": "Type : marché_couvert · marché_plein_air · producteur · cave...",
        "market_days": "Jours de marché",
        "market_hours": "Horaires du marché",
        "open_year_round": "Ouvert toute l'année ou saisonnier",
        "direct_sales": "Vente directe producteur",
        "tasting_available": "Dégustation sur place possible",
        "tasting_price": "Prix dégustation (0 si gratuit)",
        "tasting_booking": "Réservation nécessaire pour déguster",
        "tasting_schedule": "Horaires de dégustation",
        "local_specialty": "Produits phares (huîtres, sel, vin_blanc...)",
        "organic_certified": "Label bio ou biodynamie",
        "covered": "Marché couvert (activité possible par pluie)",
        "dogs_welcome": "Chiens acceptés",
        "best_time": "Meilleur moment pour y aller",
        "producer_story": "Courte histoire du producteur",
    },
    "Dégustations": {
        "degustation_type": "Type : vin · miel · sel · conserves · fromage · huîtres · bière",
        "nb_products_tasted": "Nombre de produits à goûter",
        "guided_by_producer": "Guidé par le producteur lui-même",
        "pairing_available": "Accord mets/produits proposé",
        "purchase_possible": "Achat possible sur place après dégustation",
        "group_booking": "Disponible pour groupes, EVG, EVJF",
        "sensory_description": "Description sensorielle depuis les avis",
    },
    "Nautisme": {
        "activity_type": "Sports : surf · voile · kayak · paddle · char_à_voile · kitesurf",
        "level_available": "Niveaux : débutant · intermédiaire · expert",
        "equipment_provided": "Matériel fourni (combinaison, etc.)",
        "booking_required": "Réservation obligatoire",
        "group_size_max": "Nombre max de participants par session",
        "price_per_person": "Tarif par personne en €",
        "session_duration_min": "Durée d'une session en minutes",
        "instructor_languages": "Langues des moniteurs",
        "outdoor_only": "Activité en plein air (dépend météo)",
        "tide_dependent": "Dépend des marées",
        "certification": "Délivre un brevet ou diplôme",
        "seasonal_only": "Ouvert uniquement en saison",
        "season_start": "Début de saison (ex: 01-04)",
        "season_end": "Fin de saison (ex: 30-09)",
    },
    "Villages & Sites": {
        "site_type": "Type : port · quartier_historique · village_médiéval · site_mégalithique...",
        "visit_type": "Visite : libre · guidé · les deux",
        "guided_tour_available": "Visite guidée disponible",
        "guided_tour_price": "Prix visite guidée en €",
        "guided_tour_languages": "Langues des visites guidées",
        "audio_guide": "Audioguide disponible",
        "free_access": "Accès libre et gratuit",
        "indoor_outdoor": "Intérieur · extérieur · mixte",
        "best_time": "Meilleur moment pour visiter",
        "seasonal_events": "Événements saisonniers",
        "kids_activities": "Animations enfants",
        "photo_spot": "Lieu très photographié",
        "classified": "Labels officiels (Monument Historique, etc.)",
        "tide_sensitive": "Accès dépendant des marées",
    },
    "Châteaux & Monuments": {
        "monument_type": "Type : château · prieuré · abbaye · fort · église · tour · chapelle",
        "historical_period": "Période historique (ex: XIe siècle)",
        "visit_type": "Visite : libre · guidé · les deux",
        "guided_tour_available": "Visite guidée disponible",
        "guided_tour_price": "Supplément visite guidée en €",
        "guided_tour_languages": "Langues des visites guidées",
        "audio_guide": "Audioguide disponible",
        "climbable": "Peut-on monter (tour, donjon, clocher)",
        "stairs_count": "Nombre de marches si on peut monter",
        "view_from_top": "Vue panoramique depuis le sommet",
        "indoor_outdoor": "Intérieur · extérieur · mixte",
        "free_access": "Accès libre et gratuit",
        "classified": "Labels : Monument Historique, Classé MH...",
        "renovation_status": "État de rénovation (ex: Réouverture été 2026)",
        "kids_activities": "Animations enfants, jeux médiévaux",
        "seasonal_events": "Événements saisonniers (son et lumière, fête médiévale...)",
        "photo_spot": "Lieu très photographié",
        "best_time": "Meilleur moment pour visiter",
    },
    "Musées & Culture": {
        "museum_type": "Type : art · histoire · sciences · nature · maritime · écomusée · insolite",
        "collection_theme": "Thème de la collection (ex: Art contemporain, Coquillages)",
        "permanent_collection": "Collection permanente disponible",
        "temporary_exhibition": "Expositions temporaires régulières",
        "visit_duration_min": "Durée recommandée en minutes",
        "guided_tour_available": "Visite guidée disponible",
        "guided_tour_languages": "Langues des visites guidées",
        "audio_guide": "Audioguide disponible",
        "rainy_day_activity": "Idéal par temps de pluie",
        "kids_friendly": "Adapté et intéressant pour les enfants",
        "kids_workshop": "Ateliers enfants disponibles",
        "photo_allowed": "Photos autorisées",
        "classified": "Labels et reconnaissances officielles",
        "accessibility_full": "Musée 100% accessible PMR",
        "gift_shop": "Boutique souvenirs sur place",
        "cafe_on_site": "Café ou restaurant dans le musée",
    },
    "Jeux & Divertissement": {
        "activity_type": "Type : karting · laser_game · trampoline · escape_game · accrobranche...",
        "indoor_outdoor": "Intérieur · extérieur · mixte",
        "age_max": "Âge maximum si applicable",
        "height_min_cm": "Taille minimum en cm (karting, accrobranche)",
        "booking_required": "Réservation obligatoire",
        "group_size_min": "Nombre minimum de participants",
        "group_size_max": "Nombre maximum par session",
        "session_duration_min": "Durée d'une session en minutes",
        "price_per_person": "Tarif par personne en €",
        "equipment_provided": "Équipement fourni",
        "rainy_day_activity": "Idéal par temps de pluie",
        "multi_activity": "Plusieurs activités sur le même site",
        "activity_levels": "Niveaux : débutant · intermédiaire · expert",
        "adrenaline_level": "Niveau d'adrénaline : faible · modéré · fort",
        "kids_only_zone": "Espace séparé petits enfants",
        "snack_bar": "Restauration ou snack sur place",
        "half_day_possible": "Peut y passer une demi-journée",
        "full_day_possible": "Journée entière possible",
    },
    "Parcs animaliers": {
        "park_type": "Type : zoo · ferme_pédagogique · parc_animalier · refuge",
        "nb_species": "Nombre d'espèces animales",
        "animal_interaction": "Nourrir ou toucher les animaux possible",
        "guided_tour": "Visite guidée disponible",
        "shows_available": "Spectacles ou démonstrations",
        "full_day_possible": "Journée entière possible",
        "kids_only_zone": "Espace dédié petits enfants",
        "snack_bar": "Restauration sur place",
        "picnic_area": "Aires pique-nique disponibles",
        "stroller_ok": "Accessible poussette sur tout le site",
        "rainy_day_activity": "Abris suffisants pour la pluie",
    },
    "Aquariums": {
        "nb_species": "Nombre d'espèces marines",
        "touch_tank": "Bassin tactile (toucher raies, étoiles de mer)",
        "shark_tank": "Requins visibles",
        "feeding_show": "Spectacle de nourrissage",
        "indoor_only": "Toujours en intérieur",
        "kids_workshop": "Ateliers pédagogiques enfants",
        "gift_shop": "Boutique souvenirs sur place",
    },
    "Parcs botaniques": {
        "garden_type": "Type : botanique · floral · bambouseraie · jardin_public",
        "nb_plant_species": "Nombre d'espèces végétales",
        "free_access": "Accès libre et gratuit",
        "picnic_area": "Aires pique-nique",
        "playground": "Jeux enfants sur place",
        "animals_on_site": "Animaux présents (canards, poneys...)",
        "shade_level": "Ombre : ombragé · semi-ombragé · exposé",
        "seasonal_bloom": "Période de floraison (ex: avril-juin)",
        "stroller_ok": "Accessible poussette",
    },
    "Cinéma": {
        "nb_screens": "Nombre de salles",
        "vf_available": "Version française disponible",
        "vost_available": "Version originale sous-titrée",
        "outdoor_screening": "Projection en plein air",
        "bar_on_site": "Bar sur place",
        "rainy_day_activity": "Activité par temps de pluie (toujours oui)",
    },
    "Bars & Ambiance": {
        "bar_type": "Type : bar_port · rooftop · cocktails · guinguette · bar_plage",
        "terrace": "Terrasse disponible",
        "terrace_view": "Vue depuis terrasse : mer · port · falaises",
        "live_music": "Concerts ou musique live",
        "open_late": "Ouvert après minuit",
        "happy_hour": "Happy hour disponible",
        "cocktail_specialty": "Spécialité cocktail",
        "dogs_welcome": "Chiens acceptés en terrasse",
        "seasonal_only": "Ouvert uniquement en saison",
    },
    "Casino & Jeux": {
        "casino_type": "Type : grand_casino · salle_de_jeux",
        "nb_slot_machines": "Nombre de machines à sous",
        "nb_electronic_games": "Jeux électroniques",
        "nb_tables": "Tables de jeux (blackjack, roulette, poker)",
        "games_available": "Jeux disponibles",
        "evening_tables": "Tables ouvertes uniquement le soir",
        "evening_tables_hours": "Horaires des tables (ex: à partir de 21h)",
        "dress_code": "Tenue correcte exigée",
        "restaurant_on_site": "Restaurant sur place",
        "shows_available": "Spectacles ou concerts",
        "open_late": "Ouvert après minuit",
    },
    "Piscines & Spa": {
        "facility_type": "Type : thalasso · piscine_municipale · spa · centre_aquatique",
        "sea_water": "Eau de mer chauffée (thalasso)",
        "treatments_available": "Soins et massages disponibles",
        "outdoor_pool": "Piscine extérieure",
        "indoor_pool": "Piscine intérieure",
        "water_slides": "Toboggans aquatiques",
        "jacuzzi": "Jacuzzi disponible",
        "sauna_hammam": "Sauna ou hammam",
        "kids_pool": "Pataugeoire petits enfants",
        "booking_required": "Réservation obligatoire",
        "day_pass_available": "Accès journée sans hébergement",
        "day_pass_price": "Prix du pass journée en €",
    },
}


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        pois = json.load(f)
    print(f"Loaded {len(pois)} POIs")

    for poi in pois:
        subcat = poi.get("subcategory", "")

        # --- Socle commun : ajouter les champs manquants en null ---
        for field in SOCLE_FIELDS:
            if field not in poi:
                poi[field] = None

        # --- Specific : ajouter les champs manquants en null ---
        specific_def = SPECIFIC_FIELDS.get(subcat, {})
        if specific_def:
            if "specific" not in poi or poi["specific"] is None:
                poi["specific"] = {}
            if "specific_status" not in poi or poi["specific_status"] is None:
                poi["specific_status"] = {}

            for field_key in specific_def:
                if field_key not in poi["specific"]:
                    poi["specific"][field_key] = None
                if field_key not in poi["specific_status"]:
                    poi["specific_status"][field_key] = "empty"

        # --- Ajouter les labels FR ---
        labels = {}
        # Socle
        for field, desc in SOCLE_FIELDS.items():
            labels[field] = desc
        # Specific
        for field, desc in specific_def.items():
            labels[f"specific.{field}"] = desc
        poi["_labels"] = labels

    # Save
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)
    print(f"JSON updated with full schema + labels FR")

    # Count
    for poi in pois[:3]:
        subcat = poi.get("subcategory", "")
        specific = poi.get("specific", {})
        filled = sum(1 for v in specific.values() if v is not None)
        total = len(specific)
        print(f"  [{poi['id']}] {subcat}: {filled}/{total} specific fields filled")

    # Update dashboard
    if os.path.exists(DASHBOARD_PATH):
        try:
            with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
                html = f.read()
            mini = json.dumps(pois, ensure_ascii=True, separators=(",", ":"))
            marker = "const EMBEDDED_DATA = "
            start = html.index(marker) + len(marker)
            end = html.index("];", start) + 1
            html = html[:start] + mini + html[end:]
            with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"Dashboard updated")
        except Exception as e:
            print(f"Dashboard update failed: {e}")


if __name__ == "__main__":
    main()
