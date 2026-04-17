"""
core/config.py
==============
Central configuration — reads from environment variables.
Supports .env files for local development.
"""

import os
from dotenv import load_dotenv
from groq import Groq

# Load environment variables from .env file if it exists
load_dotenv()

# ── Groq ────────────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY not found in environment variables or .env file. "
        "Please ensure it is set correctly."
    )

groq_client = Groq(api_key=GROQ_API_KEY)

# ── Model names (overridable via env) ───────────────────────────────────────────
QUESTION_MODEL  = os.getenv("QUESTION_MODEL", "llama-3.1-8b-instant")
EVAL_MODEL      = os.getenv("EVAL_MODEL",     "llama-3.1-8b-instant")
TOTAL_QUESTIONS = 15   # 6 easy + 5 medium + 4 hard

# ── CORS ────────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv("VERCEL_ORIGIN", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)

# ── Azure TTS ───────────────────────────────────────────────────────────────────
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "centralindia")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "en-IN-ArjunNeural")

# ── Database ────────────────────────────────────────────────────────────────────
# DATABASE_URL is the single source of truth consumed by database.py (psycopg2).
# sslmode=require is mandatory for Supabase connections.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:your_db_password@db.your-project-ref.supabase.co:5432/postgres?sslmode=require",
)
# Ensure sslmode is always present (guards against .env entries missing the param)
if "sslmode" not in DATABASE_URL:
    DATABASE_URL += "?sslmode=require"

DB_HOST     = os.getenv("DB_HOST",     "db.your-project-ref.supabase.co")
DB_PORT     = os.getenv("DB_PORT",     "5432")
DB_NAME     = os.getenv("DB_NAME",     "postgres")
DB_USER     = os.getenv("DB_USER",     "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "your_db_password")
DB_SSLMODE  = os.getenv("DB_SSLMODE",  "require")