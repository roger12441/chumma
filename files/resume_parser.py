"""
resume_parser.py
================
Parses uploaded resumes (PDF, DOCX, Images) using local libraries and Groq LLM
to match the M1 parsing output format (CandidateProfile).
"""

import fitz  # PyMuPDF
from docx import Document
import tempfile
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import re
import asyncio
from fastapi import UploadFile

from config import QUESTION_MODEL
from llm import llm_call, safe_json
from schemas import CandidateProfile

MIN_TEXT_THRESHOLD = 200

# ── 1. Text Extraction (From IMPLEMENTATION_PLAN.TXT) ──────────────────────────

def clean_text(text: str) -> str:
    text = re.sub(r'\r', '', text)
    text = re.sub(r'\n+', '\n', text)
    return text.strip()

async def extract_text(file: UploadFile) -> str:
    suffix = file.filename.split(".")[-1].lower()

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{suffix}") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    text = ""

    # -----------------------------
    # PDF Extraction (Block-based)
    # -----------------------------
    if suffix == "pdf":
        try:
            doc = fitz.open(tmp_path)
            all_blocks = []

            for page in doc:
                blocks = page.get_text("blocks")
                blocks.sort(key=lambda b: (b[1], b[0]))  # y0, x0 sorting

                for block in blocks:
                    block_text = block[4].strip()
                    if block_text:
                        all_blocks.append(block_text)

            text = "\n".join(all_blocks)
            text = clean_text(text)

        except Exception as e:
            print("PDF extraction error:", e)

        print("Block Extraction Text Length:", len(text))

        # OCR fallback
        if len(text.strip()) < MIN_TEXT_THRESHOLD:
            print("Low text detected. Triggering OCR fallback...")

            try:
                images = convert_from_path(tmp_path)
                ocr_text = ""

                for img in images:
                    ocr_text += pytesseract.image_to_string(img)

                text = clean_text(ocr_text)
                print("OCR Text Length:", len(text))

            except Exception as e:
                print("OCR extraction failed:", e)

        return text

    # -----------------------------
    # DOCX Extraction
    # -----------------------------
    elif suffix == "docx":
        try:
            doc = Document(tmp_path)
            text = "\n".join([para.text for para in doc.paragraphs])
            text = clean_text(text)
            print("DOCX Text Length:", len(text))
            return text
        except Exception as e:
            print("DOCX extraction error:", e)
            return ""

    # -----------------------------
    # Image Resume Support
    # -----------------------------
    elif suffix in ["png", "jpg", "jpeg"]:
        try:
            img = Image.open(tmp_path)
            text = pytesseract.image_to_string(img)
            text = clean_text(text)
            print("Image OCR Text Length:", len(text))
            return text
        except Exception as e:
            print("Image OCR error:", e)
            return ""

    else:
        return "" 


# ── 2. Heuristic Classification (From IMPLEMENTATION_PLAN.TXT) ────────────────

MAJOR_KEYWORDS_MAP = {
    "skills": ["skill", "framework", "tools"],
    "experience": ["experience", "intern", "work"],
    "projects": ["project"],
    "education": ["education"],
    "summary": ["summary", "objective"],
    "certifications": ["certification", "award", "achievement"]
}

def classify_sections(sections):
    structured = {
        "executive_summary": "",
        "skills": "",
        "projects": "",
        "experience": "",
        "education": "",
        "certifications": "",
        "other": []
    }

    for section in sections:
        header = section["header"].lower()
        content = section.get("content", "").strip()

        matched = False

        for key, keywords in MAJOR_KEYWORDS_MAP.items():
            if any(keyword in header for keyword in keywords):
                if key == "summary":
                    structured["executive_summary"] += content + "\n"
                else:
                    structured[key] += content + "\n"

                matched = True
                break

        if not matched:
            structured["other"].append(section)

    return structured


# ── 3. High-Level Parser ───────────────────────────────────────────────────────

async def parse_resume(file: UploadFile) -> CandidateProfile:
    """
    Extracts text from the uploaded file and uses the LLM to cleanly map
    the extracted information directly into the CandidateProfile schema.
    """
    text = await extract_text(file)
    
    if not text.strip():
        # Fallback to empty candidate profile if text extraction failed
        return CandidateProfile(candidate_name="Unknown Candidate")

    system_prompt = "You are an expert resume parser. You ONLY return valid JSON. Do not add markdown."
    user_prompt = f"""
Analyze the following resume text and extract the candidate's details.
Return STRICT JSON matching this schema:
{{
  "candidate_name": "Full Name",
  "skills": "Comma separated list of skills",
  "projects": "Brief summary of projects",
  "experience": "Brief summary of work experience",
  "education": "Brief summary of education",
  "certifications": "Comma separated list of certifications",
  "Additional_Information": ["Any other notable details"]
}}

Resume Text:
{text}
"""
    try:
        raw = llm_call(system_prompt, user_prompt, QUESTION_MODEL, max_tokens=1500)
        data = safe_json(raw)
    except Exception as e:
        print("Failed to map resume with LLM:", e)
        data = {}

    return CandidateProfile(
        candidate_name=data.get("candidate_name") or "Candidate",
        skills=data.get("skills") or "",
        projects=data.get("projects") or "",
        experience=data.get("experience") or "",
        education=data.get("education") or "",
        certifications=data.get("certifications") or "",
        Additional_Information=data.get("Additional_Information") or [],
        speech_transcript=""
    )
