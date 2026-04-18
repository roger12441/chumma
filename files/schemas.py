"""
models/schemas.py
=================
All Pydantic request / response models used across the application.
Keeping them in one place avoids circular imports and makes it trivial
to generate an OpenAPI client from a single source of truth.
"""

from typing import List, Optional
from pydantic import BaseModel


# ── Verification ─────────────────────────────────────────────────────────────────

class VerifySessionRequest(BaseModel):
    candidate_name: Optional[str] = None   # name returned by face-verification service
    vercel_origin:  Optional[str] = None   # Vercel URL that triggered the call (audit log)


class VerifySessionResponse(BaseModel):
    verify_token:   str
    candidate_name: Optional[str]
    message:        str


# ── Candidate profile (from Module 1 / resume parser) ───────────────────────────

class CandidateProfile(BaseModel):
    candidate_name:         Optional[str]  = None
    skills:                 Optional[str]  = ""
    projects:               Optional[str]  = ""
    experience:             Optional[str]  = ""
    education:              Optional[str]  = ""
    certifications:         Optional[str]  = ""
    Additional_Information: Optional[list] = []
    speech_transcript:      Optional[str]  = ""
    # Tracks the interview session (generated on resume upload)
    session_id:             Optional[str]  = None
    # Portal passes this after face-verification completes
    verify_token:           Optional[str]  = None


# ── Questions ────────────────────────────────────────────────────────────────────

class Question(BaseModel):
    id:         int
    difficulty: str   # easy | medium | hard
    category:   str   # technical | project | behavioural | general
    question:   str


class QuestionsResponse(BaseModel):
    session_id:       str
    candidate_name:   Optional[str]
    face_verified:    bool
    total:            int
    questions:        List[Question]
    question_source:  Optional[str] = "llm"   # "llm" or "fallback_bank"


# ── Answer evaluation ────────────────────────────────────────────────────────────

class CandidateAnswer(BaseModel):
    question_id:      int
    candidate_answer: str


class EvaluateRequest(BaseModel):
    session_id:     str
    candidate_name: Optional[str] = None
    answers:        List[CandidateAnswer]


class QuestionResult(BaseModel):
    question_id:      int
    difficulty:       str
    question:         str
    candidate_answer: str
    score:            int     # 0–10
    feedback:         str
    badge:            str     # Excellent | Good | Acceptable | Needs Work | No Attempt


class EvaluateResponse(BaseModel):
    candidate_name: Optional[str]
    total_score:    int
    max_score:      int
    percentage:     float
    grade:          str
    summary:        str
    submitted_at:   str       # ISO timestamp used in report header
    results:        List[QuestionResult]
