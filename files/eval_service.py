"""
services/eval_service.py
========================
Business logic for Groq Call 2: lenient per-answer scoring and grading.

Keeps all scoring logic, prompt engineering, and grade calculation
separate from the HTTP layer.
"""

import json
from datetime import datetime, timezone
from typing import List

from fastapi import HTTPException
from schemas import EvaluateRequest, EvaluateResponse, QuestionResult
from config import EVAL_MODEL
from store import SESSION_STORE
from llm import llm_call, safe_json
import database as db


# ── Prompt templates ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a lenient and fair technical interview evaluator.
You evaluate candidate answers generously, rewarding partial understanding.
You ONLY return valid JSON. No explanations outside the JSON."""

_USER_PROMPT_TEMPLATE = """
Evaluate these candidate answers. Be LENIENT and GENEROUS in scoring.

Scoring rubric:
  0     = completely blank / "idk" / totally irrelevant
  1-3   = attempted but mostly wrong or missing the point
  4-5   = partial understanding, touches on the topic but missing key parts
  6-7   = mostly correct with minor gaps or imprecision
  8-9   = solid answer, covers key points well
  10    = excellent — accurate, complete, well-articulated

Leniency rules:
  - If the candidate shows ANY relevant knowledge, score at least 4
  - Short but correct answers still score 7+
  - Do NOT penalise casual language or informal explanations
  - Hard questions (difficulty=hard) should be graded with extra leniency
  - Reward the intent and direction of the answer, not just perfection

Answers to evaluate:
{eval_payload}

Return STRICT JSON only in this format:
{{
  "evaluations": [
    {{
      "id": <question_id>,
      "score": <integer 0-10>,
      "feedback": "<2 sentence constructive feedback>",
      "badge": "<Excellent|Good|Acceptable|Needs Work|No Attempt>"
    }},
    ...
  ],
  "overall_summary": "<2-3 sentence summary of the candidate's overall performance>"
}}

Badge rules:
  Excellent   = score 9-10
  Good        = score 7-8
  Acceptable  = score 5-6
  Needs Work  = score 1-4
  No Attempt  = score 0
"""


# ── Grade table ──────────────────────────────────────────────────────────────────

def _calculate_grade(percentage: float) -> str:
    if percentage >= 90: return "A+"
    if percentage >= 80: return "A"
    if percentage >= 70: return "B"
    if percentage >= 60: return "C"
    if percentage >= 50: return "D"
    return "F"


# ── Public service function ──────────────────────────────────────────────────────

def evaluate_candidate(req: EvaluateRequest) -> EvaluateResponse:
    """
    1. Guards against missing / already-submitted sessions.
    2. Bundles answers + ideal answers into a single Groq call.
    3. Clamps scores to 0–10 and maps them to badges.
    4. Calculates total score, percentage, and letter grade.
    5. Marks the session as submitted (prevents re-evaluation).
    """

    # ── Session guards ─────────────────────────────────────────────────────────
    session = SESSION_STORE.get(req.session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail="Session not found. Call /generate_questions first.",
        )
    if session.get("submitted"):
        raise HTTPException(
            status_code=409,
            detail="Answers already submitted for this session. Each session can only be evaluated once.",
        )

    questions_map    = {q.id: q for q in session["questions"]}
    ideal_answer_map = session["ideal_answers"]

    # ── Build evaluation payload ───────────────────────────────────────────────
    eval_items = _build_eval_items(req.answers, questions_map, ideal_answer_map)
    if not eval_items:
        raise HTTPException(status_code=400, detail="No valid answers matched session questions.")

    eval_payload = json.dumps(eval_items, indent=2)

    # ── Call Groq ─────────────────────────────────────────────────────────────
    user_prompt = _USER_PROMPT_TEMPLATE.format(eval_payload=eval_payload)
    raw  = llm_call(_SYSTEM_PROMPT, user_prompt, EVAL_MODEL, max_tokens=3000)
    data = safe_json(raw)

    evaluations  = {e["id"]: e for e in data.get("evaluations", [])}
    summary_text = data.get("overall_summary", "Evaluation complete.")

    # ── Build result list ──────────────────────────────────────────────────────
    results: List[QuestionResult] = _build_results(eval_items, evaluations)

    # ── Score aggregation ──────────────────────────────────────────────────────
    total_score = sum(r.score for r in results)
    max_score   = len(results) * 10
    percentage  = round((total_score / max_score) * 100, 1) if max_score else 0.0
    grade       = _calculate_grade(percentage)

    candidate_name = req.candidate_name or session.get("candidate_name") or "Candidate"
    submitted_at   = datetime.now(timezone.utc).isoformat()

    # ── Mark session as submitted (in-memory) ─────────────────────────────────
    session["submitted"]    = True
    session["submitted_at"] = submitted_at

    # ── Persist to Supabase ───────────────────────────────────────────────────
    ordinal_to_uuid = session.get("ordinal_to_uuid", {})
    db.save_answer_evaluations(
        session_id      = req.session_id,
        results         = results,
        ordinal_to_uuid = ordinal_to_uuid,
    )
    db.save_interview_result(
        session_id  = req.session_id,
        total_score = total_score,
        max_score   = max_score,
        percentage  = percentage,
        grade       = grade,
        summary     = summary_text,
    )
    db.mark_session_submitted(
        session_id   = req.session_id,
        submitted_at = submitted_at,
    )

    return EvaluateResponse(
        candidate_name = candidate_name,
        total_score    = total_score,
        max_score      = max_score,
        percentage     = percentage,
        grade          = grade,
        summary        = summary_text,
        submitted_at   = submitted_at,
        results        = results,
    )


# ── Private helpers ──────────────────────────────────────────────────────────────

def _build_eval_items(answers, questions_map, ideal_answer_map) -> list:
    """Merge candidate answers with their questions and ideal answers."""
    items = []
    for ans in answers:
        q = questions_map.get(ans.question_id)
        if not q:
            continue
        items.append({
            "id"               : ans.question_id,
            "difficulty"       : q.difficulty,
            "question"         : q.question,
            "ideal_answer"     : ideal_answer_map.get(ans.question_id, ""),
            "candidate_answer" : ans.candidate_answer.strip() or "(no answer provided)",
        })
    return items


def _build_results(eval_items: list, evaluations: dict) -> List[QuestionResult]:
    """Convert raw LLM evaluation dicts into validated QuestionResult objects."""
    results = []
    for item in eval_items:
        ev    = evaluations.get(item["id"], {})
        # Clamp score to valid range — LLM may occasionally exceed bounds
        score = max(0, min(10, int(ev.get("score", 0))))
        results.append(QuestionResult(
            question_id      = item["id"],
            difficulty       = item["difficulty"],
            question         = item["question"],
            candidate_answer = item["candidate_answer"],
            score            = score,
            feedback         = ev.get("feedback", "No feedback available."),
            badge            = ev.get("badge", "Needs Work"),
        ))
    return results
