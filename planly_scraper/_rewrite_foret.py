"""Script temporaire : réécrit process_forets_nature dans scraper_missing.py"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

with open("planly_scraper/scraper_missing.py", encoding="utf-8") as f:
    content = f.read()

NEW_FUNC = r'''def process_forets_nature(client, poi: dict, report: list) -> dict:
    """Pipeline Forets & Nature — 5 blocs avec fetch direct AllTrails/Komoot."""
    from bs4 import BeautifulSoup

    poi_name = poi.get("name", "")
    specific = poi.setdefault("specific", {})
    status   = poi.setdefault("specific_status", {})

    def _already(key):
        return status.get(key) in ("auto", "manual") and specific.get(key) is not None

    def _set(key, val, src):
        specific[key] = val
        status[key]   = "auto"
        report.append({"poi": poi_name, "field": key, "value": val, "status": "auto",
                        "sources": src if isinstance(src, list) else [src]})
        log.info(f"  [F&N] OK {key} = {val}")

    def _empty(key):
        if not _already(key):
            status[key] = "empty"
            log.info(f"  [F&N] -- {key} = null")

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    }

    def _fetch_soup(url):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            log.warning(f"  [F&N] fetch failed {url[:60]}: {e}")
            return None

    def _soup_text(soup, max_chars=8000):
        return soup.get_text(separator=" ", strip=True)[:max_chars] if soup else ""

    log.info(f"  [F&N] == {poi_name} ==")

    # -------------------------------------------------------------------------
    # BLOC 1 : superficie_ha + sentiers_km_total
    # Sources : website ONF -> Wikipedia -> SERP snippets
    # -------------------------------------------------------------------------
    if not (_already("superficie_ha") and _already("sentiers_km_total")):
        log.info("  [F&N] B1: superficie + sentiers_km")
        text_b1, src_b1 = "", []

        website = poi.get("website") or ""
        if "onf.fr" in website:
            soup = _fetch_soup(website)
            if soup:
                text_b1 = _soup_text(soup, 5000)
                src_b1  = [website]
                log.info(f"  [F&N] B1 source: ONF {website[:60]}")

        if not text_b1:
            snip_w = search_organic(f"{poi_name} wikipedia superficie hectares", depth=5)
            wiki_url = next((s["url"] for s in snip_w if "wikipedia.org" in s.get("url", "")), None)
            if wiki_url:
                soup = _fetch_soup(wiki_url)
                if soup:
                    text_b1 = _soup_text(soup, 5000)
                    src_b1  = [wiki_url]
                    log.info(f"  [F&N] B1 source: Wikipedia {wiki_url[:60]}")
            if not text_b1:
                text_b1 = _snippets_to_text(snip_w)
                src_b1  = [s.get("url", "") for s in snip_w[:3]]

        if text_b1:
            prompt_b1 = (
                f'Texte source sur "{poi_name}" :\n\n{text_b1}\n\n'
                "Cherche UNIQUEMENT les patterns :\n"
                "- superficie_ha : entier avant \"hectares\" ou \"ha\"\n"
                "- sentiers_km_total : entier avant \"km de sentiers\" ou \"kilometres de sentiers\"\n\n"
                '{"superficie_ha": <int|null>, "sentiers_km_total": <int|null>}'
            )
            r = _call_haiku(client, prompt_b1)
            if r and isinstance(r, dict):
                for key in ("superficie_ha", "sentiers_km_total"):
                    if not _already(key):
                        val = r.get(key)
                        _set(key, val, src_b1) if val is not None else _empty(key)
        else:
            _empty("superficie_ha"); _empty("sentiers_km_total")
    else:
        log.info("  [F&N] B1: skip (deja rempli)")

    # -------------------------------------------------------------------------
    # BLOC 2 : nb_parcours via fetch direct AllTrails
    # -------------------------------------------------------------------------
    alltrails_url = specific.get("alltrails_url")
    if not _already("nb_parcours") and alltrails_url:
        log.info(f"  [F&N] B2: nb_parcours via AllTrails")
        soup = _fetch_soup(alltrails_url)
        if soup:
            prompt_b2 = (
                f'Texte d\'une page AllTrails sur "{poi_name}" :\n\n{_soup_text(soup, 4000)}\n\n'
                "Cherche le nombre TOTAL d'itineraires affiche sur la page (ex: \"16 itineraires\", \"5 randonnees\").\n"
                "C'est le total global, pas le nombre de sentiers listes.\n"
                '{"nb_parcours": <int|null>}'
            )
            r = _call_haiku(client, prompt_b2)
            if r and isinstance(r, dict) and r.get("nb_parcours") is not None:
                _set("nb_parcours", r["nb_parcours"], alltrails_url)
            else:
                _empty("nb_parcours")
        else:
            _empty("nb_parcours")
    elif not _already("nb_parcours"):
        _empty("nb_parcours")
    else:
        log.info(f"  [F&N] B2: skip (deja rempli: {specific.get('nb_parcours')})")

    # -------------------------------------------------------------------------
    # BLOC 3 : trails[] via fetch direct AllTrails + Komoot
    # -------------------------------------------------------------------------
    komoot_url = specific.get("komoot_url")
    trails_existing = specific.get("trails")
    if _already("trails") and isinstance(trails_existing, list) and len(trails_existing) > 0:
        log.info(f"  [F&N] B3: skip (deja rempli: {len(trails_existing)} sentiers)")
        trails = trails_existing
    else:
        log.info("  [F&N] B3: extraction trails AllTrails + Komoot")

        def _extract_trails_from_page(text, source_url):
            if not text:
                return []
            prompt_trails = (
                f'Texte extrait de "{source_url}" sur "{poi_name}" :\n\n{text[:7000]}\n\n'
                "Extrais la liste complete des sentiers.\n"
                "Differencies : rando (a pied) | vtt (velo tout terrain).\n"
                "NE PAS inclure les itineraires cyclables routiers.\n\n"
                "Pour chaque sentier :\n"
                '{"name":string,"type":"rando"|"vtt","distance_km":float|null,'
                '"duration_min":int|null,"difficulty":int 1-5|null,"trail_url":string|null}\n'
                "difficulty: 1=tres facile / 2=facile / 3=modere / 4=difficile / 5=expert\n"
                "trail_url: URL complete si presente dans le texte, sinon null.\n"
                "Retourne un tableau JSON. Si aucun sentier -> []"
            )
            result = _call_haiku(client, prompt_trails, max_tokens=2000)
            return result if isinstance(result, list) else []

        raw_trails = []

        if alltrails_url:
            soup = _fetch_soup(alltrails_url)
            if soup:
                trails_at = _extract_trails_from_page(_soup_text(soup), alltrails_url)
                log.info(f"  [F&N] B3 AllTrails -> {len(trails_at)} sentiers")
                raw_trails.extend(trails_at)

        if komoot_url:
            soup = _fetch_soup(komoot_url)
            if soup:
                trails_km = _extract_trails_from_page(_soup_text(soup), komoot_url)
                log.info(f"  [F&N] B3 Komoot -> {len(trails_km)} sentiers")
                raw_trails.extend(trails_km)

        if not raw_trails:
            log.info("  [F&N] B3 fallback SERP")
            snip4 = search_organic(
                f"{poi_name} sentiers randonnee VTT parcours distance difficulte", depth=8)
            text4 = _snippets_to_text(snip4, max_chars=6000)
            raw_trails = _extract_trails_from_page(text4, "SERP")

        # Deduplication par nom + merge des champs
        merged = {}
        for t in raw_trails:
            key = (t.get("name") or "").lower().strip()
            if not key:
                continue
            if key not in merged:
                merged[key] = dict(t)
            else:
                for f in ("distance_km", "duration_min", "difficulty", "trail_url"):
                    if merged[key].get(f) is None and t.get(f) is not None:
                        merged[key][f] = t[f]
        trails = list(merged.values())

        # Completer les champs null
        for t in trails:
            missing_f = [f for f in ("distance_km", "duration_min", "difficulty") if t.get(f) is None]
            if not missing_f:
                continue
            if t.get("trail_url"):
                soup = _fetch_soup(t["trail_url"])
                if soup:
                    fields_str = ", ".join(f'"{f}": <valeur|null>' for f in missing_f)
                    r = _call_haiku(client,
                        f'Texte sur "{t["name"]}" :\n{_soup_text(soup, 3000)}\n'
                        f"Extrais : {{{fields_str}}}\n"
                        "distance_km:float  duration_min:int(minutes)  difficulty:int 1-5")
                    if r and isinstance(r, dict):
                        for f in missing_f:
                            if r.get(f) is not None:
                                t[f] = r[f]
                        continue
            still_m = [f for f in missing_f if t.get(f) is None]
            if still_m:
                snip_t = search_organic(f"{t['name']} randonnee distance duree difficulte", depth=3)
                txt_t  = _snippets_to_text(snip_t, 2000)
                if txt_t:
                    fields_str = ", ".join(f'"{f}": <valeur|null>' for f in still_m)
                    r = _call_haiku(client, f'Texte sur "{t["name"]}" :\n{txt_t}\nExtrais : {{{fields_str}}}')
                    if r and isinstance(r, dict):
                        for f in still_m:
                            if r.get(f) is not None:
                                t[f] = r[f]
            if not t.get("trail_url"):
                snip_u = search_organic(f"{t['name']} alltrails", depth=3)
                for s in snip_u:
                    url = s.get("url", "")
                    if "alltrails.com" in url and t.get("name", "").lower()[:8] in url.lower():
                        t["trail_url"] = url
                        break

        specific["trails"] = trails
        status["trails"] = "auto" if trails else "empty"
        nb_r = sum(1 for t in trails if t.get("type") == "rando")
        nb_v = sum(1 for t in trails if t.get("type") in ("vtt", "velo"))
        report.append({"poi": poi_name, "field": "trails", "value": len(trails),
                        "status": status["trails"],
                        "sources": [alltrails_url or "", komoot_url or ""]})
        log.info(f"  [F&N] B3 OK trails = {len(trails)} ({nb_r} rando, {nb_v} VTT)")

    # nb_parcours depuis trails si encore vide
    if not _already("nb_parcours") and trails:
        _set("nb_parcours", len(trails), "trails_count")

    # Selection display
    display = _select_display_trails(trails)
    specific["trails_display"] = display
    status["trails_display"] = "auto" if (display["rando"] or display["vtt"]) else "empty"
    log.info(f"  [F&N] display = {len(display['rando'])} rando + {len(display['vtt'])} VTT")

    # -------------------------------------------------------------------------
    # BLOC 4 : playground + wildlife_observable
    # -------------------------------------------------------------------------
    keys_b4 = [k for k in ("playground", "wildlife_observable") if not _already(k)]
    if keys_b4:
        log.info("  [F&N] B4: playground + wildlife_observable")
        snip4 = search_organic(f"{poi_name} aire de jeux enfants faune animaux", depth=5)
        text4 = _snippets_to_text(snip4, 4000)
        if text4:
            prompt_b4 = (
                f'Texte source sur "{poi_name}" :\n\n{text4}\n\n'
                "playground = true si 'aire de jeux', 'jeux pour enfants', 'playground' mentionne.\n"
                "wildlife_observable = true si faune mentionnee (chevreuil, sanglier, oiseau, renard, cerf, lapin, rapace).\n"
                "Retourne UNIQUEMENT true, false ou null.\n"
                '{"playground": <true|false|null>, "wildlife_observable": <true|false|null>}'
            )
            r = _call_haiku(client, prompt_b4)
            if r and isinstance(r, dict):
                src4 = [s.get("url", "") for s in snip4[:3]]
                for key in keys_b4:
                    val = r.get(key)
                    _set(key, val, src4) if val is not None else _empty(key)
        else:
            for key in keys_b4:
                _empty(key)
    else:
        log.info("  [F&N] B4: skip (deja rempli)")

    # -------------------------------------------------------------------------
    # BLOC 5 : corriger statut alltrails_url / komoot_url
    # -------------------------------------------------------------------------
    for key in ("alltrails_url", "komoot_url"):
        if specific.get(key) and status.get(key) not in ("auto", "manual"):
            status[key] = "auto"
            log.info(f"  [F&N] B5: statut {key} corrige -> auto")

    return poi

'''

old_start_marker = 'def process_forets_nature(client, poi: dict, report: list) -> dict:\n    """Pipeline'
old_end_marker   = '\n\ndef get_missing_base_fields'

idx_s = content.find(old_start_marker)
idx_e = content.find(old_end_marker, idx_s)

if idx_s < 0 or idx_e < 0:
    print("ERROR: markers not found", idx_s, idx_e)
    sys.exit(1)

new_content = content[:idx_s] + NEW_FUNC + '\n\ndef get_missing_base_fields' + content[idx_e + len('\n\ndef get_missing_base_fields'):]

with open("planly_scraper/scraper_missing.py", "w", encoding="utf-8") as f:
    f.write(new_content)

print("Done — scraper_missing.py rewritten")
