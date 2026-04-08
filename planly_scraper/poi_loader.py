import re
import openpyxl
from config import EXCEL_PATH, EXCEL_SHEET


def _clean_emoji(text: str) -> str:
    """Supprime les emojis en tête d'une chaîne."""
    if not text:
        return text
    # Supprime les emojis unicode en début de chaîne + espaces
    return re.sub(r"^[\U00010000-\U0010ffff\u200d\u2600-\u27bf\ufe0f\u2764]+\s*", "", text).strip()


def _make_tag(name: str) -> str:
    """Génère un tag/id slug à partir du nom du POI."""
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


def load_pois() -> list[dict]:
    """Charge les POIs depuis le fichier Excel.

    Returns:
        Liste de dicts avec les clés :
        tag, name, category, subcategory, commune, status_note
    """
    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True)
    ws = wb[EXCEL_SHEET]

    pois = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        category_raw, subcategory, name, commune, status_note = row[:5]

        # Ignorer les lignes vides ou la ligne TOTAL
        if not name or (category_raw and category_raw.strip().upper() == "TOTAL"):
            continue

        category = _clean_emoji(category_raw) if category_raw else ""
        status_note = status_note or ""

        pois.append({
            "tag": _make_tag(name),
            "name": name.strip(),
            "category": category,
            "subcategory": (subcategory or "").strip(),
            "commune": (commune or "").strip(),
            "status_note": _clean_emoji(status_note),
        })

    wb.close()
    return pois


if __name__ == "__main__":
    pois = load_pois()
    print(f"Loaded {len(pois)} POIs")
    for p in pois[:5]:
        print(f"  [{p['tag']}] {p['name']} — {p['commune']}")
