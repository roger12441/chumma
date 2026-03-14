import os
import aiofiles
import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException, Response
from pydantic import BaseModel
from groq import Groq
import uuid
import azure.cognitiveservices.speech as speechsdk

# Assume config validation covers GROQ_API_KEY
from config import GROQ_API_KEY, AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, DEFAULT_VOICE

router = APIRouter(prefix="/stt", tags=["Speech-To-Text", "Text-To-Speech"])
client = Groq(api_key=GROQ_API_KEY)

class TTSRequest(BaseModel):
    text: str
    voice: str | None = None

def synthesize_text(text: str, voice: str | None = None):
    selected_voice = voice if voice else DEFAULT_VOICE

    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY,
        region=AZURE_SPEECH_REGION
    )

    speech_config.speech_synthesis_voice_name = selected_voice

    # Do not use speaker output in API service
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=None
    )

    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    else:
        raise Exception(f"Speech synthesis failed: {result.reason}")

@router.post("/synthesize")
async def tts_endpoint(req: TTSRequest):
    """
    Accepts text and an optional voice, synthesizes speech, and returns the audio stream (WAV).
    """
    try:
        audio_data = await asyncio.to_thread(synthesize_text, req.text, req.voice)
        return Response(content=audio_data, media_type="audio/wav")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Accepts an audio file via multipart/form-data, saves it temporarily,
    sends it to Groq's whisper-large-v3 model, and returns the transcription.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Save to a temporary file, as the Groq client requires a file path reading
    ext = os.path.splitext(file.filename)[1] or ".webm"
    temp_file_path = f"/tmp/{uuid.uuid4()}{ext}"

    try:
        # Write the audio blob to disk
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024):  # read in 1MB chunks
                await out_file.write(content)

        # Call Groq Whisper API
        def run_transcription():
            with open(temp_file_path, "rb") as audio_file:
                return client.audio.transcriptions.create(
                    file=audio_file,
                    model="whisper-large-v3",
                    response_format="verbose_json",
                    language="en",
                    prompt="This audio contains a person speaking in an interview or self-introduction setting. The speech is conversational English where the speaker may describe their background, education, experiences, interests, or answer questions."
                )

        transcription = await asyncio.to_thread(run_transcription)
        
        # Determine how Groq returns the text
        # (verbose_json returns an object that has a .text attribute/key)
        result_text = transcription.text if hasattr(transcription, "text") else transcription.get("text", "")

        return {
            "status": "success",
            "text": result_text
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)