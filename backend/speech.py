import httpx
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from config import client, ELEVENLABS_API_KEY, DEFAULT_VOICE_ID, text_corrector, logger

async def process_audio_transcription(audio_bytes: bytes, filename: str) -> str:
    try:
        transcription = await client.audio.transcriptions.create(
            file=(filename or "audio.webm", audio_bytes),
            model="whisper-large-v3",
            response_format="json",
            temperature=0.0,
        )
        return text_corrector.clean_text_stream(transcription.text.strip())
    except Exception as e:
        logger.error(f"Whisper processing error: {e}")
        raise HTTPException(status_code=500, detail="Transcription failed.")

def generate_tts_stream(text: str, voice_id: str) -> StreamingResponse:
    voice = voice_id.strip() or DEFAULT_VOICE_ID
    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=500, detail="ElevenLabs credentials missing.")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    body = {
        "text": text, "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.75, "similarity_boost": 0.85, "style_exaggeration": 0.15},
    }

    async def audio_stream():
        async with httpx.AsyncClient() as http:
            async with http.stream("POST", url, headers=headers, json=body, timeout=30.0) as r:
                if r.status_code != 200: return
                async for chunk in r.aiter_bytes(): yield chunk

    return StreamingResponse(audio_stream(), media_type="audio/mpeg")