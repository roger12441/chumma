"""
main.py
=======
Application entry point — the ONLY file you need to run.

  Development:
    GROQ_API_KEY=your_key uvicorn main:app --host 0.0.0.0 --port 8001 --reload

  Production (lock CORS to your Vercel deployment):
    GROQ_API_KEY=your_key \
    VERCEL_ORIGIN=https://your-project.vercel.app \
    uvicorn main:app --host 0.0.0.0 --port 8001

  Swagger UI: http://localhost:8001/docs

Module map
──────────
  main.py                      ← you are here (FastAPI app + CORS + router wiring)
  core/
    config.py                  ← env vars, Groq client, model names, CORS origins
    store.py                   ← in-memory session dicts (swap for Redis in prod)
  models/
    schemas.py                 ← all Pydantic request / response models
  services/
    llm.py                     ← Groq wrapper (llm_call + safe_json)
    question_service.py        ← Groq Call 1 logic (question generation)
    eval_service.py            ← Groq Call 2 logic (answer evaluation + grading)
  routers/
    verification.py            ← POST /verification/create_session
    questions.py               ← POST /questions/generate  |  GET /questions/{id}
    evaluation.py              ← POST /evaluation/evaluate_answers
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Config must be imported first — it validates GROQ_API_KEY at startup
from config import ALLOWED_ORIGINS
from store import SESSION_STORE, VERIFIED_SESSIONS

# Routers
from verification import router as verification_router
from questions    import router as questions_router
from evaluation   import router as evaluation_router
from stt          import router as stt_router
from resume_router import router as resume_router

# Path to the project root (one level up from files/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── App ──────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "Question_AI — Module 2",
    description = (
        "AI Interview Brain: face-verification gating, "
        "question generation, and lenient answer evaluation via Groq."
    ),
    version     = "3.1.0",
)

# ── CORS ─────────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ALLOWED_ORIGINS,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
    expose_headers    = ["X-Session-Token"],
)

# ── Routers ───────────────────────────────────────────────────────────────────────
# Prefix summary:
#   /verification/create_session
#   /questions/generate
#   /questions/{session_id}
#   /evaluation/evaluate_answers

app.include_router(verification_router)
app.include_router(questions_router)
app.include_router(evaluation_router)
app.include_router(stt_router)
app.include_router(resume_router)

# ── Health check ──────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health():
    return {
        "status"           : "ok",
        "module"           : "Module 2 — AI Interview Brain",
        "version"          : "3.1.0",
        "active_sessions"  : len(SESSION_STORE),
        "pending_verifies" : len(VERIFIED_SESSIONS),
        "cors_origins"     : ALLOWED_ORIGINS,
        "vercel_mode"      : ALLOWED_ORIGINS != ["*"],
    }


# ── Debug Portal ──────────────────────────────────────────────────────────────────

@app.get("/debug", tags=["Portal"], include_in_schema=False)
def debug_portal():
    """Serve the debug portal HTML directly from FastAPI."""
    html_path = PROJECT_ROOT / "debug_portal.html"
    return FileResponse(html_path, media_type="text/html")


# ── Dev runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
