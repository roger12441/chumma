"""
resume_router.py
================
HTTP layer for resume parser.
"""

from fastapi import APIRouter, File, UploadFile
from schemas import CandidateProfile
from resume_parser import parse_resume

import uuid
from datetime import datetime, timezone
from typing import Optional
import database as db

router = APIRouter(tags=["Resume"])

@router.post("/upload_resume", response_model=CandidateProfile)
async def upload_resume(
    file: UploadFile = File(...),
    session_id: Optional[str] = None
):
    """
    Accepts a resume file, extracts text, generates a session (if new),
    and saves/updates the candidate profile in the database.
    """
    # 1. Parse resume
    profile = await parse_resume(file)
    
    # 2. Assign/Generate session_id
    if not session_id:
        session_id = str(uuid.uuid4())
    
    profile.session_id = session_id
    
    # 3. Create/Update session in DB
    created_at = datetime.now(timezone.utc).isoformat()
    db.save_interview_session(
        session_id     = session_id,
        candidate_name = profile.candidate_name or "Candidate",
        face_verified  = False, # Not verified yet
        origin_url     = None,
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
    
    return profile
