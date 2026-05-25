"""
image_utils.py — Règles qualité images partagées entre tous les scripts Planly.

Importé par : enrich_images.py, download_images.py, dataforseo.py
"""
import os, hashlib
from PIL import Image

# ── Constantes ──────────────────────────────────────────────────────────────

MIN_SIDE_PX     = 600    # côté minimum en pixels
MAX_RATIO       = 2.8    # ratio max largeur/hauteur (trop aplati/panoramique)
MAX_WIDTH       = 1920   # largeur max — resize si dépassé
PHASH_THRESHOLD = 5      # distance Hamming max pour doublon perceptuel (0=identique, 5=quasi-identique, >15=différent)

WATERMARK_DOMAINS = [
    "alamy.com", "123rf.com", "shutterstock.com", "gettyimages.",
    "dreamstime.com", "depositphotos.com", "fotolia.com", "istockphoto.com",
    "stock.adobe", "pond5.com", "bigstockphoto.com", "ftcdn.net",
]


# ── Vérifications URL ────────────────────────────────────────────────────────

def is_watermarked(url: str) -> bool:
    """Retourne True si l'URL pointe vers un site de stock avec watermark visible."""
    return any(d in url.lower() for d in WATERMARK_DOMAINS)


# ── Format détection ─────────────────────────────────────────────────────────

def detect_format(path: str) -> str:
    """Détecte le vrai format depuis les magic bytes. Retourne 'jpeg', 'png' ou 'webp'."""
    with open(path, "rb") as f:
        header = f.read(12)
    if header[:2] == b"\xff\xd8":
        return "jpeg"
    if header[:4] == b"\x89PNG":
        return "png"
    if header[:4] == b"RIFF" or b"WEBP" in header[:12]:
        return "webp"
    return "jpeg"  # défaut conservateur


def media_type_from_path(path: str) -> str:
    """Retourne le media_type correct pour Claude API, basé sur les magic bytes (pas l'extension)."""
    fmt = detect_format(path)
    return {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[fmt]


# ── Conversion & normalisation ────────────────────────────────────────────────

def normalize_to_jpeg(path: str) -> str:
    """
    Convertit WebP/PNG en JPEG en place, normalise l'extension en .jpg.
    Retourne le chemin final (peut être différent si conversion nécessaire).
    """
    fmt = detect_format(path)
    base = os.path.splitext(path)[0]
    jpg_path = base + ".jpg"

    if fmt in ("webp", "png"):
        img = Image.open(path).convert("RGB")
        img.save(jpg_path, "JPEG", quality=85, optimize=True)
        if path != jpg_path:
            os.unlink(path)
        return jpg_path

    # JPEG avec mauvaise extension (.jpeg → .jpg)
    if path != jpg_path:
        os.rename(path, jpg_path)
        return jpg_path

    return path


def resize_if_needed(path: str) -> None:
    """Réduit la largeur à MAX_WIDTH si trop grande. Modifie le fichier en place."""
    img = Image.open(path)
    w, h = img.size
    if w > MAX_WIDTH:
        new_h = int(h * MAX_WIDTH / w)
        img = img.resize((MAX_WIDTH, new_h), Image.LANCZOS)
        img.save(path, "JPEG", quality=85, optimize=True)


# ── Géométrie ────────────────────────────────────────────────────────────────

def check_geometry(path: str) -> tuple[bool, str]:
    """
    Vérifie taille et ratio de l'image.
    Retourne (ok, raison) — raison vide si ok.
    """
    try:
        img = Image.open(path)
        w, h = img.size
        mn = min(w, h)
        ratio = max(w, h) / mn if mn else 999
        if mn < MIN_SIDE_PX:
            return False, f"trop_petit({w}x{h})"
        if ratio > MAX_RATIO:
            return False, f"trop_aplati({w}x{h} r={ratio:.1f})"
        return True, ""
    except Exception as e:
        return False, f"erreur_lecture({e})"


def is_portrait(path: str) -> bool:
    """True si l'image est en format portrait (hauteur > largeur)."""
    try:
        img = Image.open(path)
        w, h = img.size
        return h > w
    except Exception:
        return False


# ── Déduplication ────────────────────────────────────────────────────────────

def md5(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def phash(path: str):
    """Retourne le perceptual hash de l'image (imagehash.ImageHash)."""
    import imagehash
    return imagehash.phash(Image.open(path))


def is_perceptual_duplicate(path: str, seen_hashes: list) -> bool:
    """
    Vérifie si l'image est perceptuellement similaire à une image déjà vue.
    Si non, ajoute son hash à seen_hashes. Retourne True si doublon.
    """
    try:
        h = phash(path)
        for prev in seen_hashes:
            if abs(h - prev) <= PHASH_THRESHOLD:
                return True
        seen_hashes.append(h)
        return False
    except Exception:
        return False


# ── Pipeline qualité complet (pour download_images.py) ───────────────────────

def apply_quality_pipeline(path: str, url: str = "",
                            seen_md5: set = None,
                            seen_phash: list = None) -> tuple[str | None, str]:
    """
    Applique toutes les règles qualité sur une image téléchargée :
    1. Watermark (via URL)
    2. Magic bytes (vrai format)
    3. Géométrie (taille, ratio)
    4. Conversion WebP/PNG → JPEG + normalisation extension
    5. Resize max 1920px
    6. MD5 dedup
    7. pHash dedup perceptuel

    Retourne (chemin_final, raison_rejet) — chemin=None si rejeté.
    """
    if seen_md5 is None:
        seen_md5 = set()
    if seen_phash is None:
        seen_phash = []

    # 1. Watermark URL
    if url and is_watermarked(url):
        os.unlink(path)
        return None, "watermark"

    # 2. Vérifier que c'est bien une image (magic bytes)
    try:
        fmt = detect_format(path)
    except Exception:
        os.unlink(path)
        return None, "magic_bytes_invalide"

    # 3. Géométrie AVANT conversion (pour les trop petites)
    ok, raison = check_geometry(path)
    if not ok:
        os.unlink(path)
        return None, raison

    # 4. Conversion WebP/PNG → JPEG, normalisation extension
    try:
        path = normalize_to_jpeg(path)
    except Exception as e:
        os.unlink(path)
        return None, f"conversion_echouee({e})"

    # 5. Resize si > MAX_WIDTH
    try:
        resize_if_needed(path)
    except Exception:
        pass  # non bloquant

    # 6. MD5 dedup
    try:
        h = md5(path)
        if h in seen_md5:
            os.unlink(path)
            return None, "doublon_md5"
        seen_md5.add(h)
    except Exception:
        pass

    # 7. pHash dedup perceptuel
    if is_perceptual_duplicate(path, seen_phash):
        os.unlink(path)
        return None, "doublon_perceptuel"

    return path, ""
