"""Réglages du pipeline. Tout ce qu'on règle samedi est ici."""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "htf.sqlite"
OUT_DIR = DATA_DIR / "out"

# Modèles : Haiku pour le volume, Opus pour les fiches affichées.
MODEL_BULK = "claude-haiku-5-5"
MODEL_SHOWCASE = "claude-opus-5-5"
EFFORT_BULK = "low"
EFFORT_SHOWCASE = "medium"

# Prix en $ par million de tokens (entrée, sortie, lecture de cache).
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
}

# Budget : 20 € de crédit, plafond dur. On garde une marge.
BUDGET_TOTAL_USD = 18.0
BUDGET_RUN_USD = 4.0         # une annotation complète du samedi (~14 000 vidéos) est estimée à ~2 $

# Parallélisme (limites du compte Anthropic au 4/11 : 13 000 requêtes/min).
ANNOTATE_WORKERS = 16        # mesuré : 8 threads = 14 vidéos/s
SHOWCASE_WORKERS = 4
ORIANE_WORKERS = 4           # limites de débit Oriane inconnues : prudence, 429 gérés par reprise

# Embeddings locaux via Ollama.
OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "bge-m3"

# Fenêtres du score d'émergence (en jours).
WINDOW_RECENT = 3
WINDOW_BASELINE = 14

# Seuils, à régler sur les vraies données.
CLUSTER_DISTANCE = 0.50      # distance cosinus max entre sujets d'un même groupe
MIN_VIDEOS = 8               # en dessous, un sujet n'est pas classé
MIN_CREATORS = 4
COVERAGE_SIMILARITY = 0.66   # calibré le 3/11 : >0,68 même histoire, 0,60-0,68 même grand sujet
TOP_TOPICS_SHOWCASE = 20     # sujets résumés par Opus

THEMES = [
    "logement", "pouvoir d'achat", "emploi et travail", "sécurité", "justice",
    "immigration", "écologie et climat", "énergie", "santé", "éducation",
    "jeunesse", "transports", "numérique et IA", "institutions et élections",
    "international", "agriculture", "culture et médias", "égalité et discriminations",
    "autre",
]
