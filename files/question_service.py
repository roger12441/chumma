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
from question_bank import get_fallback_questions
import database as db


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

    # ── Call Groq with Retry ──────────────────────────────────────────────────
    user_prompt = _USER_PROMPT_TEMPLATE.format(profile_summary=profile_summary)
    
    MAX_RETRIES = 5
    questions = []
    raw_ideal_answers = []
    question_source = "llm"          # tracks origin: "llm" or "fallback_bank"
    
    for attempt in range(MAX_RETRIES):
        try:
            raw  = llm_call(_SYSTEM_PROMPT, user_prompt, QUESTION_MODEL, max_tokens=3000)
            data = safe_json(raw)

            raw_questions     = data.get("questions", [])
            raw_ideal_answers = data.get("ideal_answers", [])

            if not raw_questions:
                raise ValueError("LLM returned no questions.")

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
            
            # successfully parsed and structured questions
            print(f"✅ Questions generated from LLM on attempt {attempt + 1}/{MAX_RETRIES} for '{candidate_name}'.")
            break
            
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                # ── FALLBACK: LLM exhausted → use predefined question bank ────────
                print(
                    f"⚠️  LLM failed after {MAX_RETRIES} attempts. "
                    f"Activating fallback question bank for '{candidate_name}'."
                )
                questions = get_fallback_questions(profile)
                raw_ideal_answers = []     # no ideal answers from the bank
                question_source = "fallback_bank"
                print(f"📦 Questions retrieved from FALLBACK BANK for '{candidate_name}'. Total: {len(questions)}")
            else:
                print(f"Groq question generation failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying...")

    print(f"🔖 Session for '{candidate_name}' — question_source: {question_source}")

    # ── Persist session ───────────────────────────────────────────────────────
    session_id     = profile.session_id or str(uuid.uuid4())
    created_at     = datetime.now(timezone.utc).isoformat()
    ideal_answers_map = {a["id"]: a.get("ideal_answer", "") for a in raw_ideal_answers}

    SESSION_STORE[session_id] = {
        "candidate_name"  : candidate_name,
        "face_verified"   : face_verified,
        "questions"       : questions,
        "ideal_answers"   : ideal_answers_map,
        "ordinal_to_uuid" : {},           # populated after DB write below
        "question_source" : question_source,
        "created_at"      : created_at,
        "submitted"       : False,
        "submitted_at"    : None,
        # store profile for DB persistence reference
        "_profile"        : profile,
    }

    # ── Persist to Supabase ───────────────────────────────────────────────────
    db.save_interview_session(
        session_id     = session_id,
        candidate_name = candidate_name,
        face_verified  = face_verified,
        origin_url     = getattr(profile, "vercel_origin", None),
        created_at     = created_at,
    )
    db.save_candidate_profile(
        session_id            = session_id,
        skills                = profile.skills or "",
        projects              = profile.projects or "",
        experience            = profile.experience or "",
        education             = profile.education or "",
        certifications        = profile.certifications or "",
        speech_transcript     = profile.speech_transcript or "",
        additional_information= profile.Additional_Information or [],
    )
    ordinal_to_uuid = db.save_questions_and_ideal_answers(
        session_id    = session_id,
        questions     = questions,
        ideal_answers = ideal_answers_map,
    )
    # Store the UUID mapping in-memory so evaluations can resolve it
    SESSION_STORE[session_id]["ordinal_to_uuid"] = ordinal_to_uuid

    return QuestionsResponse(
        session_id      = session_id,
        candidate_name  = candidate_name,
        face_verified   = face_verified,
        total           = len(questions),
        questions       = questions,
        question_source = question_source,
    )


def fetch_session_questions(session_id: str) -> QuestionsResponse:
    """Return questions for an existing session (portal-reload safety)."""
    session = SESSION_STORE.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    return QuestionsResponse(
        session_id      = session_id,
        candidate_name  = session["candidate_name"],
        face_verified   = session.get("face_verified", False),
        total           = len(session["questions"]),
        questions       = session["questions"],
        question_source = session.get("question_source", "llm"),
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
