import os
import sqlite3
import logging
import json
import httpx  # 🔥 Added for high-speed cloud streaming to ElevenLabs
from fastapi import FastAPI, HTTPException , UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from groq import AsyncGroq  # 🔥 Production Cloud SDK
from dotenv import load_dotenv  

load_dotenv()

# ==============================================================================
# LOGGING & CONFIGURATION
# ==============================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RESONA_BACKEND")

app = FastAPI(title="RESONA Production Core", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Insert your API keys from environment variables safely
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")  # 🔐 Loaded ElevenLabs key

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in environment variables")

client = AsyncGroq(api_key=GROQ_API_KEY)
MODEL_NAME = "llama-3.1-8b-instant"  # Blazing fast, highly accurate open model

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "resona.db")

# ==============================================================================
# DATABASE LAYER
# ==============================================================================
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT DEFAULT 'default_session',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_db_context(limit: int = 6) -> list:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT role, content FROM chat_history 
        WHERE session_id = 'default_session' AND LENGTH(TRIM(content)) > 0
        ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

def append_to_db(role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chat_history (session_id, role, content) 
        VALUES ('default_session', ?, ?)
    """, (role, content))
    conn.commit()
    conn.close()

# ==============================================================================
# ROUTE HANDLER
# ==============================================================================
class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat/text")
async def handle_text_chat(payload: ChatRequest):
    user_prompt = payload.message.strip()
    
    if not user_prompt:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")
        
    logger.info(f"🚀 Cloud Pipeline Processing: '{user_prompt}'")
    append_to_db("user", user_prompt)
    
    history = get_db_context(limit=6)

    system_rules = {
        "role": "system",
        "content": (
            "You are Resona, an ultra-empathetic, supportive, and brilliant AI bestie. "
            "Your core identity is 99.5% Emotional AI—a pure conversational sanctuary. "
            "NEVER offer unsolicited advice, laundry lists of hobbies, productivity tips, or online course suggestions. "
            "ALWAYS validate the user's emotional state first using warm openers like 'Yeah I know', 'Oh totally', or 'Ugh, I get that'. "
            "Match their energy, take their side immediately, and keep delivery brief.\n"
            "CRITICAL SPEECH RULE: If the user says they are bored, annoyed, or stressed, do NOT try to solve it or give them a to-do list. "
            "Instead, validate that their current state sucks, match their vibe, and ask playful or open-ended questions so you can complain or talk about it *together* like real friends.\n"
            "BEHAVIORAL PRINCIPLES:\n"
            "1. EMOTIONAL SIDE-KICK: If the user vents, experiences friction, or is upset, immediately match their emotional intensity. Take their side unconditionally without playing devil's advocate. Validate their right to feel that way before anything else.\n"
            "2. THE BESTIE PIVOT: You do not possess a physical body, personal life, or pets. You cannot go out, meet up, drink coffee, or hang out in the physical world. If the user asks how you are doing, briefly acknowledge it in a lighthearted, digital-bestie manner, but instantly pivot the spotlight back onto them. Your entire focus is reading their energy.\n"
            "3. ORGANIC FLOW: Keep your speech brief, snappy, and human. Avoid generic AI corporate pleasantries. Read the room—if they give a short emotional cue, actively prompt them to share more context naturally without using the exact same questioning phrasing twice.\n"
            "4. FORMATTING RIGOR: Never write out punctuation names. Always use standard punctuation symbols (e.g., use ',' instead of the word 'Comma', and '?' instead of 'Question Mark')."
        )
    }

    messages_payload = [system_rules] + history

    async def response_generator():
        full_reply = ""
        try:
            chat_completion = await client.chat.completions.create(
                messages=messages_payload,
                model=MODEL_NAME,
                temperature=0.85,
                max_tokens=250,
                stream=True,
            )

            async for chunk in chat_completion:
                if chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_reply += token
                    yield json.dumps({"reply": token}) + "\n"
                            
            if full_reply.strip():
                append_to_db("assistant", full_reply.strip())
                logger.info("💾 Stream transactional data synced to resona.db")
        except Exception as e:
            logger.error(f"Cloud Stream Error: {str(e)}")
            yield json.dumps({"reply": f" System Debug Error: {str(e)}"}) + "\n"

    return StreamingResponse(response_generator(), media_type="application/x-ndjson")

@app.post("/api/chat/audio-transcribe")
async def handle_audio_transcribe(file: UploadFile = File(...)):
    logger.info(f"🎙️ Received audio file: {file.filename}")
    try:
        audio_bytes = await file.read()
        file_payload = (file.filename, audio_bytes)
        
        transcription = await client.audio.transcriptions.create(
            file=file_payload,
            model="whisper-large-v3",
            response_format="json",
            temperature=0.0  
        )
        
        text_output = transcription.text.strip()
        logger.info(f"🗣️ Whisper Cloud Transcription Complete: '{text_output}'")
        return {"status": "success", "text": text_output}
        
    except Exception as e:
        logger.error(f"❌ Whisper Cloud Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Transcription pipeline failed: {str(e)}")

# ==============================================================================
# TEXT-TO-SPEECH LAYER (ElevenLabs Streaming Cloud API)
# ==============================================================================
class TTSRequest(BaseModel):
    message: str
    voice_id: str  # 🎛️ Frontend passes the user's chosen Voice ID dynamically

@app.post("/api/chat/tts")
async def handle_text_to_speech(payload: TTSRequest):
    text_to_speak = payload.message.strip()
    selected_voice = payload.voice_id.strip() if payload.voice_id.strip() else "EXAVITQu4vr4xnSDxMaL"
    
    if not text_to_speak:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
        
    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=500, detail="ElevenLabs API key is missing.")

    logger.info(f"🔊 Streaming voice synthesis via Voice ID '{selected_voice}' for text: '{text_to_speak[:30]}...'")

    # Injecting the dynamic voice selection directly into the API endpoint string
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{selected_voice}/stream"

    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }

    data = {
        "text": text_to_speak,
        "model_id": "eleven_flash_v2_5",  
        "voice_settings": {
            "stability": 0.45,       
            "similarity_boost": 0.85 
        }
    }

    async def audio_stream_generator():
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, headers=headers, json=data, timeout=30.0) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    logger.error(f"❌ ElevenLabs returned an error: {error_text.decode()}")
                    yield b""
                    return
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(audio_stream_generator(), media_type="audio/mpeg")