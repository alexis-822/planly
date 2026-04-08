import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# --- DataForSEO ---
DATAFORSEO_LOGIN = os.environ.get("DATAFORSEO_LOGIN", "")
DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD", "")
DATAFORSEO_BASE_URL = "https://api.dataforseo.com/v3"

# --- Anthropic ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL_CREATIVE = "claude-sonnet-4-6"  # descriptions, tags, conseil_planly
CLAUDE_MODEL_EXTRACT = "claude-haiku-4-5-20251001"  # extraction champs structurés, parsing

# --- Chemins ---
EXCEL_PATH = os.path.join(os.path.dirname(__file__), "..", "planly_poi_types.xlsx")
EXCEL_SHEET = "Types de POI"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
OUTPUT_GLOBAL = os.path.join(os.path.dirname(__file__), "output_global.json")

# --- Paramètres pipeline ---
BATCH_SIZE = 10  # POIs par batch DataForSEO
TASK_WAIT_SECONDS = 60  # Attente après POST des tasks
REVIEW_WAIT_SECONDS = 30  # Attente après POST des reviews
REVIEW_DEPTH = 5  # Nombre d'avis à récupérer
IMAGE_DEPTH = 10  # Nombre d'images SERP à récupérer (on en prend plus pour filtrer)
MAX_PHOTOS = 3  # Photos max par POI (après filtrage qualité)
MIN_IMAGE_WIDTH = 800  # Largeur minimum en pixels pour accepter une image
WIKIPEDIA_SUMMARY_MAX = 500  # Caractères max du résumé Wikipedia
CLAUDE_BATCH_SIZE = 10  # POIs par batch Claude (rate limit)
