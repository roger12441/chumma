"""
routers/evaluation.py
=====================
HTTP layer for answer evaluation.
Delegates all scoring logic to services/eval_service.py.
"""

from fastapi import APIRouter
from schemas import EvaluateRequest, EvaluateResponse
from eval_service import evaluate_candidate

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])


@router.post("/evaluate_answers", response_model=EvaluateResponse)
def evaluate_answers(req: EvaluateRequest):
    """
    Groq Call 2.
    Accepts a session_id and all candidate answers.
    Returns per-question scores, badges, feedback, overall grade, and timestamp.
    Each session can only be evaluated once (double-submission is rejected with 409).
    """
    return evaluate_candidate(req)
