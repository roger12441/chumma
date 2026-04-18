"""
database.py
===========
Supabase / PostgreSQL persistence layer.

All DB writes are non-blocking from the caller's perspective
(fire-and-forget wrappers so a DB hiccup never crashes the API response).

Tables written to:
  interview_sessions   — one row per session
  candidate_profiles   — one row per session (resume details)
  questions            — 15 rows per session
  ideal_answers        — up to 15 rows per session
  answer_evaluations   — 15 rows per evaluation
  interview_results    — one row per evaluation
"""

import json
import logging
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
from config import DATABASE_URL

log = logging.getLogger(__name__)

# ── Connection helper ─────────────────────────────────────────────────────────────

@contextmanager
def _get_conn():
    """Yield a psycopg2 connection from the DATABASE_URL and commit/close on exit."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Public API ────────────────────────────────────────────────────────────────────

def save_interview_session(
    *,
    session_id: str,
    candidate_name: str,
    face_verified: bool,
    origin_url: Optional[str],
    created_at: str,
) -> None:
    """Insert a row into interview_sessions."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO interview_sessions
                        (id, candidate_name, face_verified, origin_url, created_at, submitted, submitted_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        candidate_name = EXCLUDED.candidate_name,
                        face_verified  = EXCLUDED.face_verified
                    """,
                    (
                        session_id,
                        candidate_name,
                        face_verified,
                        origin_url,
                        _parse_dt(created_at),
                        False,
                        None,
                    ),
                )
        log.info("DB ✅ interview_sessions saved for session %s", session_id)
    except Exception:
        log.error("DB ❌ Failed to save interview_session %s:\n%s", session_id, traceback.format_exc())


def save_candidate_profile(
    *,
    session_id: str,
    skills: str,
    projects: str,
    experience: str,
    education: str,
    certifications: str,
    speech_transcript: str,
    additional_information: list,
) -> None:
    """Insert a row into candidate_profiles."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO candidate_profiles
                        (session_id, skills, projects, experience, education,
                         certifications, speech_transcript, additional_information)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE SET
                        skills                = EXCLUDED.skills,
                        projects              = EXCLUDED.projects,
                        experience            = EXCLUDED.experience,
                        education             = EXCLUDED.education,
                        certifications        = EXCLUDED.certifications,
                        speech_transcript     = EXCLUDED.speech_transcript,
                        additional_information= EXCLUDED.additional_information
                    """,
                    (
                        session_id,
                        skills,
                        projects,
                        experience,
                        education,
                        certifications,
                        speech_transcript,
                        json.dumps(additional_information),
                    ),
                )
        log.info("DB ✅ candidate_profiles saved for session %s", session_id)
    except Exception:
        log.error("DB ❌ Failed to save candidate_profile %s:\n%s", session_id, traceback.format_exc())


def save_questions_and_ideal_answers(
    *,
    session_id: str,
    questions: list,             # list of Question objects (ordinal id 1..15)
    ideal_answers: dict,         # { ordinal_id (int): ideal_answer_text (str) }
) -> dict:
    """
    Insert into questions and ideal_answers.

    Returns a mapping { ordinal_id (int): question_uuid (str) }
    so callers can store it alongside the session for later use in evaluations.
    """
    ordinal_to_uuid: dict = {}
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                for q in questions:
                    q_uuid = str(uuid.uuid4())
                    ordinal_to_uuid[q.id] = q_uuid

                    cur.execute(
                        """
                        INSERT INTO questions
                            (id, session_id, ordinal_number, difficulty, category, question_text)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            q_uuid,
                            session_id,
                            q.id,          # ordinal 1..15
                            q.difficulty,
                            q.category,
                            q.question,
                        ),
                    )

                    ideal_text = ideal_answers.get(q.id, "")
                    if ideal_text:
                        cur.execute(
                            """
                            INSERT INTO ideal_answers (question_id, ideal_answer_text)
                            VALUES (%s, %s)
                            ON CONFLICT (question_id) DO NOTHING
                            """,
                            (q_uuid, ideal_text),
                        )

        log.info("DB ✅ questions + ideal_answers saved for session %s (%d questions)", session_id, len(questions))
    except Exception:
        log.error("DB ❌ Failed to save questions for session %s:\n%s", session_id, traceback.format_exc())

    return ordinal_to_uuid


def save_answer_evaluations(
    *,
    session_id: str,
    results: list,                    # list of QuestionResult objects
    ordinal_to_uuid: dict,            # { ordinal_id: question_uuid }
) -> None:
    """Insert per-question evaluation rows into answer_evaluations."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                for r in results:
                    q_uuid = ordinal_to_uuid.get(r.question_id)
                    if not q_uuid:
                        log.warning("DB ⚠️  No UUID found for ordinal question_id=%s, skipping.", r.question_id)
                        continue
                    cur.execute(
                        """
                        INSERT INTO answer_evaluations
                            (session_id, question_id, candidate_answer, score, feedback, badge)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (question_id) DO UPDATE
                            SET candidate_answer = EXCLUDED.candidate_answer,
                                score            = EXCLUDED.score,
                                feedback         = EXCLUDED.feedback,
                                badge            = EXCLUDED.badge
                        """,
                        (
                            session_id,
                            q_uuid,
                            r.candidate_answer,
                            r.score,
                            r.feedback,
                            r.badge,
                        ),
                    )
        log.info("DB ✅ answer_evaluations saved for session %s (%d rows)", session_id, len(results))
    except Exception:
        log.error("DB ❌ Failed to save answer_evaluations for session %s:\n%s", session_id, traceback.format_exc())


def save_interview_result(
    *,
    session_id: str,
    total_score: int,
    max_score: int,
    percentage: float,
    grade: str,
    summary: str,
) -> None:
    """Insert a row into interview_results."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO interview_results
                        (session_id, total_score, max_score, percentage, grade, summary)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE
                        SET total_score = EXCLUDED.total_score,
                            max_score   = EXCLUDED.max_score,
                            percentage  = EXCLUDED.percentage,
                            grade       = EXCLUDED.grade,
                            summary     = EXCLUDED.summary
                    """,
                    (session_id, total_score, max_score, percentage, grade, summary),
                )
        log.info("DB ✅ interview_results saved for session %s", session_id)
    except Exception:
        log.error("DB ❌ Failed to save interview_result for session %s:\n%s", session_id, traceback.format_exc())


def mark_session_submitted(*, session_id: str, submitted_at: str) -> None:
    """Update interview_sessions.submitted = true and set submitted_at."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE interview_sessions
                    SET submitted = TRUE, submitted_at = %s
                    WHERE id = %s
                    """,
                    (_parse_dt(submitted_at), session_id),
                )
        log.info("DB ✅ interview_sessions marked submitted for session %s", session_id)
    except Exception:
        log.error("DB ❌ Failed to mark session submitted %s:\n%s", session_id, traceback.format_exc())


# ── Private helpers ───────────────────────────────────────────────────────────────

def _parse_dt(iso_str: str) -> Optional[datetime]:
    """Safely parse an ISO timestamp string to a datetime object."""
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
