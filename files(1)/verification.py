"""
routers/verification.py
=======================
HTTP layer for face-verification session management.
Single responsibility: validate the request origin, then delegate to the store.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from schemas import VerifySessionRequest, VerifySessionResponse
from config import ALLOWED_ORIGINS
from store import VERIFIED_SESSIONS

router = APIRouter(prefix="/verification", tags=["Verification"])


@router.post("/create_session", response_model=VerifySessionResponse)
def create_session(req: VerifySessionRequest, request: Request):
    """
    Called by the portal (or the Vercel face-verification app) immediately
    after the candidate passes biometric verification.

    Origin validation:
      • If VERCEL_ORIGIN is set, the HTTP Origin header must be in the allow-list.
        Localhost is always permitted so local development keeps working.
      • If VERCEL_ORIGIN is not set (dev / wildcard mode), all origins pass.

    Returns a one-use verify_token the portal forwards to /generate_questions.
    """
    _check_origin(request)

    token = str(uuid.uuid4())
    VERIFIED_SESSIONS[token] = {
        "candidate_name" : req.candidate_name,
        "verified_at"    : datetime.now(timezone.utc).isoformat(),
        "origin"         : req.vercel_origin or request.headers.get("origin", "unknown"),
    }

    return VerifySessionResponse(
        verify_token   = token,
        candidate_name = req.candidate_name,
        message        = "Face verification recorded. Proceed to resume upload.",
    )


# ── Private helper ────────────────────────────────────────────────────────────────

def _check_origin(request: Request) -> None:
    """Raise 403 if the caller's origin is not in the allow-list."""
    if ALLOWED_ORIGINS == ["*"]:
        return   # dev mode — all origins accepted

    origin       = request.headers.get("origin", "")
    is_localhost = (
        origin.startswith("http://localhost")
        or origin.startswith("http://127.0.0.1")
    )
    if not is_localhost and origin not in ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Origin '{origin}' is not authorised to create sessions. "
                f"Add it to the VERCEL_ORIGIN environment variable."
            ),
        )
