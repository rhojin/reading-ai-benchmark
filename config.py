"""All settings in one place: models, budget, concurrency and file paths."""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")  # makes OPENROUTER_API_KEY available; the key is never printed

# --- Models ------------------------------------------------------------------
# A big and a small model from two vendors. Keys are "<vendor>-<size>".
# IDs and prices (per 1M tokens, input / output) checked against
# https://openrouter.ai/api/v1/models on 2026-10-28.
# "reasoning" is sent to OpenRouter as-is. Writing six questions needs little
# thinking, so every model runs at the lowest reasoning effort it allows.
MODELS = {
    # $2.00 / $10.00 - reasoning can't be switched off for this model; "low" is its minimum
    "anthropic-big": {"id": "anthropic/claude-sonnet-5.5", "reasoning": {"effort": "low"}},
    # $0.10 / $0.50
    "anthropic-small": {"id": "anthropic/claude-haiku-5.5", "reasoning": {"effort": "none"}},
    # $2.00 / $10.00 - reasoning can't be switched off for this model; "low" is its minimum
    "openai-big": {"id": "openai/gpt-6.1-sol", "reasoning": {"effort": "low"}},
    # $0.10 / $0.50
    "openai-small": {"id": "openai/gpt-6-luna", "reasoning": {"effort": "none"}},
}

# --- Book --------------------------------------------------------------------
GUTENBERG_ID = 11  # Alice's Adventures in Wonderland (public domain)
GUTENBERG_URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"

# --- Benchmark ---------------------------------------------------------------
BUDGET_USD = 1.00  # hard stop: no new request once one run has spent this much
# (if the API key has a lower spending limit left on OpenRouter, that limit is used instead)
PARALLEL_WORKERS = 4  # requests at the same time in the "parallel, no summary" mode
RELOAD_READS = 100  # how often the "second family" read from SQLite is timed
FAMILIES = 1000  # for the cost projection in results.md

# --- OpenRouter --------------------------------------------------------------
OPENROUTER_URL = "https://openrouter.ai/api/v1"
MAX_TOKENS = 4000  # per reply, including reasoning tokens
REQUEST_TIMEOUT_S = 120
HTTP_RETRIES = 4  # on rate limits and server errors, with exponential backoff
JSON_RETRIES = 2  # extra attempts when a reply is not the JSON we asked for

# --- Files (everything stays inside this folder) ------------------------------
DB_PATH = ROOT / "benchmark.db"
BOOKS_DIR = ROOT / "books"
PROMPTS_DIR = ROOT / "prompts"
RESULTS_MD = ROOT / "results.md"
RESULTS_JSON = ROOT / "results.json"
QUESTIONS_JSON = ROOT / "questions.json"  # every model's stored question set, for readers without the database
QUALITY_REVIEW = ROOT / "quality_review.json"  # manual review of the sample questions (optional)
