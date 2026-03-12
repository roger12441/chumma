"""
core/config.py
==============
Central configuration — reads from environment variables.
All other modules import from here; nothing hardcodes env vars directly.
"""

import os
from groq import Groq

# ── Groq ────────────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY environment variable is not set. "
        "Export it before starting the server:\n"
        "  export GROQ_API_KEY=your_key_here"
    )

groq_client = Groq(api_key=GROQ_API_KEY)

# ── Model names (overridable via env) ───────────────────────────────────────────
QUESTION_MODEL  = os.getenv("QUESTION_MODEL", "llama-3.3-70b-versatile")
EVAL_MODEL      = os.getenv("EVAL_MODEL",     "llama-3.3-70b-versatile")
TOTAL_QUESTIONS = 15   # 6 easy + 5 medium + 4 hard

# ── CORS ────────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv("VERCEL_ORIGIN", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)
