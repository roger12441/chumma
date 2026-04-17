"""
Question_AI — Module 2: AI Interview Brain
==========================================
Connects to Module 1 (Resume/Profile FastAPI) → Groq LLM.

Portal flow (matches question_ai_portal.html):
  1.  Candidate opens portal → enters API URLs → clicks "Start Test"
  2.  Portal loads face-verification service in an iframe (hosted on Vercel)
  3.  On approval  → Vercel app (or portal) POSTs  POST /create_session  to register a verified candidate
  4.  Candidate uploads resume + audio → Module 1 builds profile JSON
  5.  Portal POSTs  POST /generate_questions  with profile JSON
        → Groq Call 1: 15 questions + hidden ideal answers stored in session
        → returns session_id + questions only
  6.  GET  /questions/{session_id}  — re-fetch questions (portal reload safety)
  7.  Candidate answers all 15 questions in the interview portal
  8.  Portal POSTs  POST /evaluate_answers  with session_id + answers
        → Groq Call 2: lenient per-answer scoring
        → returns scores, badges, feedback, grade, summary
  9.  Portal renders the full test report

Run:
  pip install fastapi uvicorn groq

  # Development (no origin restriction):
  GROQ_API_KEY=your_key uvicorn module2_server:app --host 0.0.0.0 --port 8001 --reload

  # Production (lock to your Vercel app):
  GROQ_API_KEY=your_key \
  VERCEL_ORIGIN=https://your-project.vercel.app \
  uvicorn module2_server:app --host 0.0.0.0 --port 8001

Swagger UI: http://localhost:8001/docs
"""

import os, json, uuid, re, io
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import azure.cognitiveservices.speech as speechsdk  # type: ignore[import-untyped]

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), "files"))
from resume_parser import parse_resume

# ── Config ─────────────────────────────────────────────────────────────────────

GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "your_groq_api_key_here")
QUESTION_MODEL  = "llama-3.3-70b-versatile"   # Call 1: question generation
EVAL_MODEL      = "llama-3.3-70b-versatile"   # Call 2: answer evaluation
TOTAL_QUESTIONS = 15                            # 6 easy + 5 medium + 4 hard

groq_client = Groq(api_key=GROQ_API_KEY)

# ── Azure TTS Config ─────────────────────────────────────────────────────────────
AZURE_SPEECH_KEY    = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "centralindia")
AZURE_TTS_VOICE     = os.getenv("DEFAULT_VOICE", "en-IN-ArjunNeural")

# ── In-Memory Stores ────────────────────────────────────────────────────────────
# verified_sessions: candidates who passed face verification
#   { verify_token: { "candidate_name": str, "verified_at": str } }
VERIFIED_SESSIONS: dict = {}

# interview sessions: created after resume upload + question generation
#   { session_id: { "questions": [...], "ideal_answers": {...},
#                   "candidate_name": str, "face_verified": bool,
#                   "created_at": str, "submitted": bool } }
SESSION_STORE: dict = {}

# ── App ─────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Question_AI — Module 2",
    description="AI Interview Brain: face-verification gating, question generation, and lenient answer evaluation via Groq.",
    version="3.0.0"
)

# ── CORS ────────────────────────────────────────────────────────────────────────
# VERCEL_ORIGIN env var should be set to your Vercel deployment URL,
# e.g.  VERCEL_ORIGIN=https://your-project.vercel.app
# Multiple origins can be comma-separated:
#   VERCEL_ORIGIN=https://your-project.vercel.app,https://your-project-git-main.vercel.app
#
# Falls back to "*" in development if not set (safe for local testing only).

_raw_origins = os.getenv("VERCEL_ORIGIN", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ALLOWED_ORIGINS,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
    expose_headers    = ["X-Session-Token"],   # lets the portal read verify_token from headers too
)

# ── Pydantic Models ─────────────────────────────────────────────────────────────

# ── Verification models ──────────────────────────────────────────────────────────
class VerifySessionRequest(BaseModel):
    candidate_name:  Optional[str] = None   # name from face-verification result
    vercel_origin:   Optional[str] = None   # Vercel URL that triggered the call (for audit)

class VerifySessionResponse(BaseModel):
    verify_token: str                      # short-lived token the portal carries into generate_questions
    candidate_name: Optional[str]
    message: str

# ── Resume / profile models ──────────────────────────────────────────────────────

class CandidateProfile(BaseModel):
    candidate_name: Optional[str] = None
    skills: Optional[str] = ""
    projects: Optional[str] = ""
    experience: Optional[str] = ""
    education: Optional[str] = ""
    certifications: Optional[str] = ""
    Additional_Information: Optional[list] = []
    speech_transcript: Optional[str] = ""
    # passed by portal after face verification completes
    verify_token: Optional[str] = None

class Question(BaseModel):
    id: int
    difficulty: str   # easy | medium | hard
    category: str     # technical | project | behavioural | general
    question: str

class QuestionsResponse(BaseModel):
    session_id: str
    candidate_name: Optional[str]
    face_verified: bool
    total: int
    questions: List[Question]

class CandidateAnswer(BaseModel):
    question_id: int
    candidate_answer: str

class EvaluateRequest(BaseModel):
    session_id: str
    candidate_name: Optional[str] = None
    answers: List[CandidateAnswer]

class QuestionResult(BaseModel):
    question_id: int
    difficulty: str
    question: str
    candidate_answer: str
    score: int           # 0–10
    feedback: str
    badge: str           # Excellent / Good / Acceptable / Needs Work / No Attempt

class EvaluateResponse(BaseModel):
    candidate_name: Optional[str]
    total_score: int
    max_score: int
    percentage: float
    grade: str
    summary: str
    submitted_at: str          # ISO timestamp — used for report header
    results: List[QuestionResult]

# ── LLM Helpers ─────────────────────────────────────────────────────────────────

def llm_call(system: str, user: str, model: str, max_tokens: int = 2500) -> str:
    """Synchronous Groq call — robustly strips markdown fences from response."""
    completion = groq_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user}
        ],
        temperature=0.6,
        max_tokens=max_tokens,
    )
    raw = completion.choices[0].message.content.strip()

    # Robust fence stripper: handles ```json, ```JSON, ``` with/without newline
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence_match:
        raw = fence_match.group(1).strip()

    return raw.strip()


def safe_json(raw: str) -> dict | list:
    """Parse JSON, raise HTTPException on failure."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {e}\nRaw: {raw[:400]}")


# ── Endpoint 0: Create Verified Session (called after face-verification passes) ──

@app.post("/verification/create_session", response_model=VerifySessionResponse)
def create_session(req: VerifySessionRequest, request: Request):
    """
    Called by the portal (or directly by the Vercel face-verification app)
    immediately after the candidate passes biometric verification.

    Origin validation:
      - If VERCEL_ORIGIN env var is set, the HTTP Origin header must match one of
        the allowed Vercel URLs.  Requests from localhost are always allowed so
        local development keeps working.
      - If VERCEL_ORIGIN is not set (dev mode / "*"), all origins are accepted.

    Returns a one-use verify_token the portal passes into /generate_questions.
    """
    # ── Origin check ──────────────────────────────────────────────────────────
    if ALLOWED_ORIGINS != ["*"]:
        origin = request.headers.get("origin", "")
        is_localhost = origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1")
        if not is_localhost and origin not in ALLOWED_ORIGINS:
            raise HTTPException(
                status_code=403,
                detail=f"Origin '{origin}' is not authorised to create sessions. "
                       f"Add it to the VERCEL_ORIGIN environment variable."
            )

    token = str(uuid.uuid4())
    VERIFIED_SESSIONS[token] = {
        "candidate_name" : req.candidate_name,
        "verified_at"    : datetime.now(timezone.utc).isoformat(),
        "origin"         : req.vercel_origin or request.headers.get("origin", "unknown"),
    }
    return VerifySessionResponse(
        verify_token   = token,
        candidate_name = req.candidate_name,
        message        = "Face verification recorded. Proceed to resume upload.",
    )


# ── Endpoint 1: Generate Questions ──────────────────────────────────────────────

@app.post("/questions/generate", response_model=QuestionsResponse)
def generate_questions(profile: CandidateProfile):
    """
    Groq Call 1.
    Accepts candidate profile + optional verify_token → generates 15 questions + ideal answers.
    - If verify_token is present and valid, the session is flagged face_verified = True.
    - Ideal answers are stored server-side only (never sent to client).
    - Returns session_id + questions only.
    """

    # ── Resolve face-verification status ──
    face_verified  = False
    verified_name  = None
    if profile.verify_token:
        vdata = VERIFIED_SESSIONS.pop(profile.verify_token, None)   # consume token (one-use)
        if vdata:
            face_verified = True
            verified_name = vdata.get("candidate_name")

    # Prefer name from face-verification result; fall back to resume-parsed name
    candidate_name = verified_name or profile.candidate_name or "Candidate"

    profile_summary = f"""
Candidate Name   : {candidate_name}
Skills           : {profile.skills}
Projects         : {profile.projects}
Experience       : {profile.experience}
Education        : {profile.education}
Certifications   : {profile.certifications}
Self-Introduction: {profile.speech_transcript}
Additional Info  : {json.dumps(profile.Additional_Information)}
""".strip()

    system_prompt = """You are an expert technical interviewer.
You generate structured interview questions based on a candidate's profile.
You ONLY return valid JSON. No explanations, no markdown, no extra text."""

    user_prompt = f"""
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

    MAX_RETRIES = 3
    questions = []
    raw_ideal_answers = []
    
    for attempt in range(MAX_RETRIES):
        try:
            raw = llm_call(system_prompt, user_prompt, QUESTION_MODEL, max_tokens=3000)
            data = safe_json(raw)

            raw_questions     = data.get("questions", [])
            raw_ideal_answers = data.get("ideal_answers", [])

            if not raw_questions:
                raise ValueError("LLM returned no questions.")

            # Build validated question list
            questions = [
                Question(
                    id         = q["id"],
                    difficulty = q.get("difficulty", "medium"),
                    category   = q.get("category", "general"),
                    question   = q["question"]
                )
                for q in raw_questions
            ]
            break
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise HTTPException(status_code=502, detail=f"LLM failed after {MAX_RETRIES} attempts: {e}")
            print(f"Groq question generation failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying...")

    # Store session
    session_id = str(uuid.uuid4())
    SESSION_STORE[session_id] = {
        "candidate_name" : candidate_name,
        "face_verified"  : face_verified,
        "questions"      : questions,
        "ideal_answers"  : {a["id"]: a.get("ideal_answer", "") for a in raw_ideal_answers},
        "created_at"     : datetime.now(timezone.utc).isoformat(),
        "submitted"      : False,
    }

    return QuestionsResponse(
        session_id     = session_id,
        candidate_name = candidate_name,
        face_verified  = face_verified,
        total          = len(questions),
        questions      = questions,
    )


# ── Endpoint 2: Fetch Questions (for portal reload) ─────────────────────────────

@app.get("/questions/{session_id}", response_model=QuestionsResponse)
def get_questions(session_id: str):
    session = SESSION_STORE.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return QuestionsResponse(
        session_id     = session_id,
        candidate_name = session["candidate_name"],
        face_verified  = session.get("face_verified", False),
        total          = len(session["questions"]),
        questions      = session["questions"],
    )


# ── Endpoint 3: Evaluate Answers ────────────────────────────────────────────────

@app.post("/evaluation/evaluate_answers", response_model=EvaluateResponse)
def evaluate_answers(req: EvaluateRequest):
    """
    Groq Call 2.
    Accepts session_id + all candidate answers.
    - Guards against double-submission (session flagged submitted=True after first call).
    - Evaluates each answer leniently via Groq.
    - Returns per-question scores, badges, feedback, overall grade, and timestamp.
    """
    session = SESSION_STORE.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Generate questions first.")

    if session.get("submitted"):
        raise HTTPException(status_code=409, detail="Answers already submitted for this session. Each session can only be evaluated once.")

    questions_map    = {q.id: q for q in session["questions"]}
    ideal_answer_map = session["ideal_answers"]

    # Build evaluation payload for batch LLM call
    eval_items = []
    for ans in req.answers:
        q = questions_map.get(ans.question_id)
        if not q:
            continue
        ideal = ideal_answer_map.get(ans.question_id, "")
        eval_items.append({
            "id"           : ans.question_id,
            "difficulty"   : q.difficulty,
            "question"     : q.question,
            "ideal_answer" : ideal,
            "candidate_answer": ans.candidate_answer.strip() or "(no answer provided)"
        })

    eval_payload = json.dumps(eval_items, indent=2)

    system_prompt = """You are a lenient and fair technical interview evaluator.
You evaluate candidate answers generously, rewarding partial understanding.
You ONLY return valid JSON. No explanations outside the JSON."""

    user_prompt = f"""
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
  - Do NOT penalize casual language or informal explanations
  - Hard questions (difficulty=hard) should be graded with extra leniency
  - Reward the intent and direction of the answer, not just perfection

Answers to evaluate:
{eval_payload}

Return STRICT JSON only in this format:
{{
  "evaluations": [
    {{
      "id": <question_id>,
      "score": <0-10>,
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

    raw  = llm_call(system_prompt, user_prompt, EVAL_MODEL, max_tokens=3000)
    data = safe_json(raw)

    evaluations  = {e["id"]: e for e in data.get("evaluations", [])}
    summary_text = data.get("overall_summary", "Evaluation complete.")

    # Build result list
    results: List[QuestionResult] = []
    for item in eval_items:
        ev = evaluations.get(item["id"], {})
        results.append(QuestionResult(
            question_id      = item["id"],
            difficulty       = item["difficulty"],
            question         = item["question"],
            candidate_answer = item["candidate_answer"],
            score            = int(ev.get("score", 0)),
            feedback         = ev.get("feedback", "No feedback available."),
            badge            = ev.get("badge", "Needs Work"),
        ))

    total_score = sum(r.score for r in results)
    max_score   = len(results) * 10
    percentage  = round((total_score / max_score) * 100, 1) if max_score else 0

    grade = (
        "A+"  if percentage >= 90 else
        "A"   if percentage >= 80 else
        "B"   if percentage >= 70 else
        "C"   if percentage >= 60 else
        "D"   if percentage >= 50 else
        "F"
    )

    candidate_name = req.candidate_name or session.get("candidate_name") or "Candidate"
    submitted_at   = datetime.now(timezone.utc).isoformat()

    # Mark session as submitted — prevents re-submission
    session["submitted"]    = True
    session["submitted_at"] = submitted_at

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


# ── STT: Transcribe Audio ────────────────────────────────────────────────────────

class SynthesizeRequest(BaseModel):
    text: str
    voice: Optional[str] = None  # override AZURE_TTS_VOICE if passed


@app.post("/stt/transcribe")
async def stt_transcribe(file: UploadFile = File(...)):
    """
    Accepts an audio file (webm, wav, mp3, m4a, ogg) and returns a JSON
    transcription produced by Groq Whisper.
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    # Groq accepts a file-like object; pass original filename so it knows the codec
    fname = file.filename or "audio.webm"
    try:
        transcription = groq_client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=(fname, io.BytesIO(audio_bytes)),
            response_format="text",
        )
        return {"status": "success", "text": transcription.strip() if isinstance(transcription, str) else str(transcription)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription error: {e}")


# ── TTS: Synthesize Text ─────────────────────────────────────────────────────────

@app.post("/stt/synthesize")
def stt_synthesize(req: SynthesizeRequest):
    """
    Converts text to speech using Azure Cognitive Services and streams back
    the audio as audio/wav.
    """
    if not AZURE_SPEECH_KEY:
        raise HTTPException(
            status_code=503,
            detail="Azure Speech key not configured. Set AZURE_SPEECH_KEY env var."
        )

    voice  = req.voice or AZURE_TTS_VOICE
    config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    config.speech_synthesis_voice_name = voice

    # Synthesize into an in-memory stream (no speaker/file needed)
    synth = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)

    result = synth.speak_text_async(req.text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        audio_data = result.audio_data
        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type="audio/wav",
            headers={"Content-Disposition": "inline; filename=speech.wav"}
        )
    elif result.reason == speechsdk.ResultReason.Canceled:
        details = speechsdk.SpeechSynthesisCancellationDetails(result)
        raise HTTPException(
            status_code=500,
            detail=f"Azure TTS canceled: {details.reason} — {details.error_details}"
        )
    else:
        raise HTTPException(status_code=500, detail="Azure TTS synthesis failed.")


# ── Resume Parser ─────────────────────────────────────────────────────────────

@app.post("/upload_resume", response_model=CandidateProfile)
async def upload_resume_endpoint(file: UploadFile = File(...)):
    return await parse_resume(file)


# ── Health Check ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status"           : "ok",
        "module"           : "Module 2 — AI Interview Brain",
        "version"          : "3.0.0",
        "active_sessions"  : len(SESSION_STORE),
        "pending_verifies" : len(VERIFIED_SESSIONS),
        "cors_origins"     : ALLOWED_ORIGINS,
        "vercel_mode"      : ALLOWED_ORIGINS != ["*"],
    }


# ── Run ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("module2_server:app", host="0.0.0.0", port=8001, reload=True)