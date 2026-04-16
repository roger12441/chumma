"""
resume_router.py
================
HTTP layer for resume parser.
"""

from fastapi import APIRouter, File, UploadFile
from schemas import CandidateProfile
from resume_parser import parse_resume

router = APIRouter(tags=["Resume"])

@router.post("/upload_resume", response_model=CandidateProfile)
async def upload_resume(file: UploadFile = File(...)):
    """
    Accepts a resume file (PDF, DOCX, Image), extracts text, and evaluates
    against Groq LLM to return a parsed CandidateProfile JSON.
    """
    profile = await parse_resume(file)
    return profile
