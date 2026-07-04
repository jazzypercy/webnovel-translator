"""
Central configuration for the Web Novel Translator.

Every tunable value lives here so the rest of the codebase doesn't have
to guess at paths, model names, or rate limits. Edit this file (or set
the environment variables it reads) rather than hunting through the
other modules.
"""

import os
from pathlib import Path

# --- Paths ---------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
RAW_CHAPTERS_DIR = BASE_DIR / "raw_chapters"
OUTPUT_DIR = BASE_DIR / "output"
GLOSSARY_PATH = BASE_DIR / "glossary.json"

# --- Gemini API ------------------------------------------------------------
# The genai.Client() picks up GEMINI_API_KEY (or GOOGLE_API_KEY) from the
# environment automatically -- see translator.py. Put your key in a .env
# file (auto-loaded if python-dotenv is installed) or export it in your
# shell. Never hardcode it here.
MODEL_NAME = os.environ.get("TRANSLATOR_MODEL", "gemini-3.5-flash")

# Free-tier Gemini Flash access is limited to roughly 10 requests per
# minute. We sleep between calls so a long batch job doesn't get hit with
# repeated 429 RESOURCE_EXHAUSTED errors. If you're on a paid tier with
# higher throughput, lower this (e.g. to 1-2 seconds).
SECONDS_BETWEEN_REQUESTS = float(os.environ.get("TRANSLATOR_DELAY", "7.0"))

# Retry behaviour for transient errors (429s, 5xxs, network blips).
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 15.0
BACKOFF_MULTIPLIER = 2.0

# Generation behaviour.
TEMPERATURE = 0.4
MAX_OUTPUT_TOKENS = 8192

# Translation tone / style guidance injected into the system prompt.
# Tweak this to taste for the series you're translating -- e.g. swap in
# "Dry, deadpan comedic tone" or "Formal, archaic register" as needed.
TRANSLATION_TONE = (
    "Modern, natural English prose suitable for a published web novel. "
    "Keep dialogue punchy and distinct per character. Avoid stiff, overly "
    "literal phrasing -- prioritize how a native English reader would "
    "naturally express the same meaning and emotional beat. Preserve the "
    "original chapter's pacing; do not add or cut content."
)

# File extension used for translated chapter output.
OUTPUT_EXTENSION = ".md"
