"""
Import des champs manquants depuis champs_manquants_new.xlsx dans output_global.json.
+ Ajout tarifs ferry Île d'Yeu.
+ Mise à jour du dashboard.
"""
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import openpyxl

SCRIPT_DIR = os.path.dirname(__file__)
XLSX_PATH = os.path.join(SCRIPT_DIR, "champs_manquants_new.xlsx")
JSON_PATH = os.path.join(SCRIPT_DIR, "output_global.json")
DASHBOARD_PATH = os.path.join(SCRIPT_DIR, "..", "dashboard.html")


def _make_tag(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[''ʼ]", "_", slug)
    slug = re.sub(r"[àâä]", "a", slug)
    slug = re.sub(r"[éèêë]", "e", slug)
    slug = re.sub(r"[îï]", "i", slug)
    slug = re.sub(r"[ôö]", "o", slug)
    slug = re.sub(r"[ùûü]", "u", slug)
    slug = re.sub(r"[ç]", "c", slug)
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


def _parse_value(raw: str, field_key: str):
    """Parse une valeur brute du Excel en valeur typée."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None

    # Booléens
    lower = raw.lower()
    if lower in ("true", "vrai", "oui", "yes"):
        return True
    if lower in ("false", "faux", "non", "no"):
        return False
    # Booléen avec commentaire : "True (chemins sableux)" → True
    if lower.startswith("true"):
        return True
    if lower.startswith("false"):
        return False

    # Numériques pour lat/lng/rating/reviews_count/distance_km
    if field_key in ("lat", "lng", "rating", "distance_km"):
        try:
            return float(raw.replace(",", "."))
        except ValueError:
            pass
    if field_key in ("reviews_count",):
        try:
            return int(raw)
        except ValueError:
            pass

    return raw


def _extract_field_key(champ: str) -> str:
    """Extrait le nom de champ depuis le format 'key (label)' ou juste 'key'."""
    match = re.match(r"^(\w+)", champ)
    return match.group(1) if match else champ


def main():
    # Load JSON
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        pois = json.load(f)
    poi_by_tag = {p["id"]: p for p in pois}
    print(f"Loaded {len(pois)} POIs from JSON")

    # Load Excel
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()
    print(f"Loaded {len(rows)} rows from Excel")

    # Process
    updated_base = 0
    updated_specific = 0
    skipped = 0

    for row in rows:
        poi_name, commune, subcategory, field_type, champ, val_actuelle, status, reponse, notoriete = row

        # Skip if no response
        if reponse is None or str(reponse).strip() == "":
            skipped += 1
            continue

        tag = _make_tag(poi_name)
        poi = poi_by_tag.get(tag)
        if not poi:
            print(f"  WARNING: POI not found: {poi_name} (tag={tag})")
            continue

        field_key = _extract_field_key(champ)
        value = _parse_value(reponse, field_key)

        if field_type == "base":
            poi[field_key] = value
            updated_base += 1
            print(f"  [{tag}] base.{field_key} = {value}")
        elif field_type == "specific":
            if "specific" not in poi:
                poi["specific"] = {}
            if "specific_status" not in poi:
                poi["specific_status"] = {}
            poi["specific"][field_key] = value
            poi["specific_status"][field_key] = "manual"
            updated_specific += 1
            print(f"  [{tag}] specific.{field_key} = {value}")

        # Update notoriété if provided
        if notoriete and str(notoriete).strip():
            poi["notoriety"] = str(notoriete).strip()

    # --- Tarifs ferry Île d'Yeu ---
    ile_yeu = poi_by_tag.get("ile_d_yeu")
    if ile_yeu:
        ile_yeu["specific"]["ferry_pricing"] = {
            "compagnie": "Compagnie Vendéenne",
            "depart_saint_gilles": {
                "ar_journee": {"adulte": 43.60, "preferentiel_60_etudiant": 38.0, "enfant_4_17": 24.0, "bebe": 6.0},
                "aller_simple": {"adulte": 21.80, "preferentiel_60_etudiant": 19.0, "enfant_4_17": 12.0, "bebe": 3.0},
            },
            "depart_fromentine": {
                "ar_journee": {"adulte": 45.60, "enfant": 24.80},
                "aller_simple": {"adulte": 22.80},
            },
            "reduction_carte_familles_nombreuses": True,
            "annee_tarifs": 2026,
        }
        ile_yeu["specific_status"]["ferry_pricing"] = "manual"
        print(f"  [ile_d_yeu] specific.ferry_pricing = tarifs 2026 ajoutés")

    # Save JSON
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)
    print(f"\nJSON saved: {updated_base} base + {updated_specific} specific updated, {skipped} skipped")

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
            print(f"Dashboard updated with {len(pois)} POIs")
        except Exception as e:
            print(f"Dashboard update failed: {e}")


if __name__ == "__main__":
    main()
