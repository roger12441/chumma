"""
services/question_service.py
============================
Business logic for Groq Call 1: question + ideal-answer generation.

Keeps all prompt engineering and session-writing in one place so the
router stays thin (HTTP concerns only).
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from schemas import CandidateProfile, Question, QuestionsResponse
from config import QUESTION_MODEL
from store import VERIFIED_SESSIONS, SESSION_STORE
from llm import llm_call, safe_json


# ── Prompt templates ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an expert technical interviewer.
You generate structured interview questions based on a candidate's profile.
You ONLY return valid JSON. No explanations, no markdown, no extra text."""

_USER_PROMPT_TEMPLATE = """
Given this candidate profile:
{profile_summary}

Generate exactly 15 interview questions split as:
- 6 EASY   — fundamental/conceptual questions on their skills or background
- 5 MEDIUM — applied/situational questions about projects and experience
- 4 HARD   — deep technical or problem-solving questions

For each question also generate an ideal reference answer (for evaluation only).

Return STRICT JSON in this exact format:
{{
  "questions": [
    {{
      "id": 1,
      "difficulty": "easy",
      "category": "technical",
      "question": "..."
    }},
    ...
  ],
  "ideal_answers": [
    {{
      "id": 1,
      "ideal_answer": "..."
    }},
    ...
  ]
}}

Rules:
- id runs 1 to 15 in order
- difficulty is exactly: easy | medium | hard
- category is one of: technical | project | behavioural | general
- Make questions specific to THIS candidate's skills and projects
- Ideal answers should be concise reference answers (2-4 sentences)
"""


# ── Public service function ──────────────────────────────────────────────────────

def create_interview_session(profile: CandidateProfile) -> QuestionsResponse:
    """
    1. Consumes the verify_token (one-use) to determine face_verified status.
    2. Calls Groq to generate 15 questions + hidden ideal answers.
    3. Persists the session to SESSION_STORE.
    4. Returns the session_id and questions only (ideal answers never leave the server).
    """

    # ── Resolve face-verification ──────────────────────────────────────────────
    face_verified = False
    verified_name = None
    if profile.verify_token:
        vdata = VERIFIED_SESSIONS.pop(profile.verify_token, None)  # one-use: pop = consume
        if vdata:
            face_verified = True
            verified_name = vdata.get("candidate_name")

    # Face-verified name takes priority over resume-parsed name
    candidate_name = verified_name or profile.candidate_name or "Candidate"

    # ── Build profile summary for the prompt ──────────────────────────────────
    profile_summary = _build_profile_summary(candidate_name, profile)

    # ── Call Groq ─────────────────────────────────────────────────────────────
    user_prompt = _USER_PROMPT_TEMPLATE.format(profile_summary=profile_summary)
    raw  = llm_call(_SYSTEM_PROMPT, user_prompt, QUESTION_MODEL, max_tokens=3000)
    data = safe_json(raw)

    raw_questions     = data.get("questions", [])
    raw_ideal_answers = data.get("ideal_answers", [])

    if not raw_questions:
        raise HTTPException(status_code=502, detail="LLM returned no questions.")

    # ── Validate + coerce question objects ────────────────────────────────────
    questions = [
        Question(
            id         = q["id"],
            difficulty = q.get("difficulty", "medium"),
            category   = q.get("category", "general"),
            question   = q["question"],
        )
        for q in raw_questions
    ]

    # ── Persist session ───────────────────────────────────────────────────────
    session_id = str(uuid.uuid4())
    SESSION_STORE[session_id] = {
        "candidate_name" : candidate_name,
        "face_verified"  : face_verified,
        "questions"      : questions,
        "ideal_answers"  : {a["id"]: a.get("ideal_answer", "") for a in raw_ideal_answers},
        "created_at"     : datetime.now(timezone.utc).isoformat(),
        "submitted"      : False,
        "submitted_at"   : None,
    }

    return QuestionsResponse(
        session_id     = session_id,
        candidate_name = candidate_name,
        face_verified  = face_verified,
        total          = len(questions),
        questions      = questions,
    )


def fetch_session_questions(session_id: str) -> QuestionsResponse:
    """Return questions for an existing session (portal-reload safety)."""
    session = SESSION_STORE.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    return QuestionsResponse(
        session_id     = session_id,
        candidate_name = session["candidate_name"],
        face_verified  = session.get("face_verified", False),
        total          = len(session["questions"]),
        questions      = session["questions"],
    )


# ── Private helpers ──────────────────────────────────────────────────────────────

def _build_profile_summary(candidate_name: str, profile: CandidateProfile) -> str:
    return f"""
Candidate Name   : {candidate_name}
Skills           : {profile.skills}
Projects         : {profile.projects}
Experience       : {profile.experience}
Education        : {profile.education}
Certifications   : {profile.certifications}
Self-Introduction: {profile.speech_transcript}
Additional Info  : {json.dumps(profile.Additional_Information)}
""".strip()
