"""Central configuration for Provenance Guard.

Constants only — the single source of truth for the model name, log path,
scoring thresholds, and the verbatim transparency labels from planning.md.
Mirrors the RepairSafe `config.py` convention.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Groq / LLM ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = "llama-3.3-70b-versatile"  # same model as Labs 1–3 / RepairSafe

# --- Audit log ---
LOG_FILE = "logs/audit.jsonl"

# --- Signal combination weights (used from Milestone 4) ---
LLM_WEIGHT = 0.6
STYLO_WEIGHT = 0.4

# --- Attribution thresholds (planning.md) ---
AI_THRESHOLD = 0.85       # combined score >= this -> likely_ai
HUMAN_THRESHOLD = 0.25    # combined score <= this -> likely_human
DISAGREE_DELTA = 0.50     # |llm - stylo| > this -> force uncertain (Milestone 4)
MIN_WORDS = 40            # below this, stylometry is unstable (Milestone 4)

VALID_ATTRIBUTIONS = {"likely_ai", "uncertain", "likely_human"}

# --- Rate limiting (applied in Milestone 5) ---
RATE_LIMIT = "10 per minute;100 per day"

# --- Transparency labels (verbatim text from planning.md) ---
LABELS = {
    "likely_ai": {
        "icon": "⚠️",
        "text": (
            "Likely AI-generated. Our analysis found strong signals that this "
            "text was produced by an AI system."
        ),
    },
    "likely_human": {
        "icon": "✓",
        "text": (
            "Likely human-written. Our analysis found no strong signals of AI "
            "generation."
        ),
    },
    "uncertain": {
        "icon": "❓",
        "text": (
            "Origin uncertain. Our analysis was inconclusive — we can't "
            "confidently attribute this text to a human or an AI. The creator "
            "can appeal this result."
        ),
    },
}
