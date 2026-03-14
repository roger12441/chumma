"""
routers/questions.py
====================
HTTP layer for question generation and retrieval.
Delegates all business logic to services/question_service.py.
"""

from fastapi import APIRouter
from schemas import CandidateProfile, QuestionsResponse
from question_service import create_interview_session, fetch_session_questions

router = APIRouter(prefix="/questions", tags=["Questions"])


@router.post("/generate", response_model=QuestionsResponse)
def generate_questions(profile: CandidateProfile):
    """
    Groq Call 1.
    Accepts a candidate profile (from Module 1 resume parser) plus an optional
    verify_token from face-verification.  Returns a session_id and 15 questions.
    Ideal answers are stored server-side only — never returned to the client.
    """
    return create_interview_session(profile)


@router.get("/{session_id}", response_model=QuestionsResponse)
def get_questions(session_id: str):
    """
    Re-fetch questions for an existing session.
    Useful when the portal reloads mid-interview and needs to restore state.
    """
    return fetch_session_questions(session_id)
