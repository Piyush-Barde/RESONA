import os
import re
import sqlite3
import logging
import json
import httpx  
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from groq import AsyncGroq 
from dotenv import load_dotenv  
from spellchecker import SpellChecker

load_dotenv()

# ==============================================================================
# LOGGING & CONFIGURATION
# ==============================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RESONA_BACKEND")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY") 
MODEL_NAME = "llama-3.1-8b-instant"  
DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "resona.db")

_WHITELIST_ENV: list[str] = [
    t.strip() for t in os.getenv("SPELL_WHITELIST", "Resona,Llama,Clash of Clans,Electro Dragons").split(",") if t.strip()
]

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in environment variables")

client = AsyncGroq(api_key=GROQ_API_KEY)

# ==============================================================================
# 🧠 0.5% INTELLIGENCE AUTO-CORRECTION ENGINE
# ==============================================================================
_SHORTHAND_MAP: dict[str, str] = {
    "idk": "I don't know", "omg": "oh my god", "woth": "with", "nd": "and",
}
_TRAILING_PUNCT_RE = re.compile(r"^(.*?)([^\w]*)$", re.DOTALL)

def _split_trailing_punct(token: str) -> tuple[str, str]:
    m = _TRAILING_PUNCT_RE.match(token)
    return (m.group(1), m.group(2)) if m else (token, "")

class UniversalTextCorrector:
    def __init__(self, whitelist: list[str] | None = None) -> None:
        self.spell = SpellChecker(distance=1)
        self._protected: set[str] = set()
        if whitelist: self._register(whitelist)

    def _register(self, terms: list[str]) -> None:
        for term in terms:
            for word in term.strip().lower().split():
                self._protected.add(word)
                self.spell.word_frequency.load_words([word])

    def clean_text_stream(self, raw: str) -> str:
        if not raw or not raw.strip(): return raw
        out: list[str] = []
        for token in raw.split():
            core, suffix = _split_trailing_punct(token)
            lower_core = core.lower()
            if len(lower_core) <= 1:
                out.append(token)
                continue
            if lower_core in _SHORTHAND_MAP:
                replacement = _SHORTHAND_MAP[lower_core]
                if core and core[0].isupper(): replacement = replacement.capitalize()
                out.append(replacement + suffix)
                continue
            if lower_core in self._protected or lower_core in self.spell:
                out.append(token)
                continue
            suggestion = self.spell.correction(lower_core)
            if suggestion and suggestion != lower_core:
                if core and core[0].isupper(): suggestion = suggestion.capitalize()
                out.append(suggestion + suffix)
            else:
                out.append(token)
        return " ".join(out)

text_corrector = UniversalTextCorrector(whitelist=_WHITELIST_ENV)

# ==============================================================================
# DATABASE LAYER
# ==============================================================================
def _get_connection() -> sqlite3.Connection:
    """Creates a thread-safe connection instance configured with performance flags."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _get_connection() as conn:
        # Added explicit DEFAULT tracking handles to protect older row structures
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT DEFAULT 'default_session',
                title TEXT DEFAULT 'New Conversation',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Create missing indexes for ultra-fast sidebar reads
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_id ON chat_history(session_id, id)")

init_db()

def get_db_context(session_id: str = "default_session", limit: int = 6) -> list:
    with _get_connection() as conn:
        rows = conn.execute("""
            SELECT role, content FROM chat_history 
            WHERE session_id = ? AND LENGTH(TRIM(content)) > 0
            ORDER BY id DESC LIMIT ?
        """, (session_id, limit)).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

def append_to_db(role: str, content: str, session_id: str = "default_session"):
    with _get_connection() as conn:
        conn.execute("""
            INSERT INTO chat_history (session_id, role, content) 
            VALUES (?, ?, ?)
        """, (session_id, role, content))

# ==============================================================================
# LIFESPAN & APP CONFIGURATION
# ==============================================================================
app = FastAPI(title="RESONA Production Core", version="3.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# PYDANTIC ROUTE SCHEMAS
# ==============================================================================
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_session"

class TTSRequest(BaseModel):
    message: str
    voice_id: str

# ==============================================================================
# ROUTE HANDLERS
# ==============================================================================
@app.post("/api/chat/text")
async def handle_text_chat(payload: ChatRequest):
    polished_message = text_corrector.clean_text_stream(payload.message.strip())
    
    if not polished_message:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")
        
    logger.info(f"🚀 Processing: '{polished_message[:40]}...' | Thread: {payload.session_id}")
    
    # 1. Check if this is a brand new conversation thread
    is_new_thread = False
    with _get_connection() as conn:
        existing_count = conn.execute(
            "SELECT COUNT(*) FROM chat_history WHERE session_id = ?", 
            (payload.session_id,)
        ).fetchone()[0]
        if existing_count == 0:
            is_new_thread = True

    # 2. Append user prompt data
    append_to_db("user", polished_message, payload.session_id)
    
    # 3. 🧠 GENERATE AUTOMATIC SIDEBAR CONVERSATION TITLE
    if is_new_thread:
        try:
            title_completion = await client.chat.completions.create(
                messages=[{
                    "role": "system", 
                    "content": "You are a title generator. Summarize the user's message into a clean, maximum 3-word title. Do not include quotes, periods, or extra commentary. Example input: 'Just coding', Output: 'Coding Session'"
                }, {"role": "user", "content": polished_message}],
                model=MODEL_NAME, temperature=0.5, max_tokens=10
            )
            generated_title = title_completion.choices[0].message.content.strip().replace('"', '')
            with _get_connection() as conn:
                conn.execute(
                    "UPDATE chat_history SET title = ? WHERE session_id = ?", 
                    (generated_title, payload.session_id)
                )
            logger.info(f"✨ Auto-Generated Sidebar Title Locked: '{generated_title}'")
        except Exception as title_err:
            logger.error(f"Failed to auto-generate thread title: {title_err}")

    # 4. Pull expanded historical context (Increased limit to 12 for better conversational tone!)
    history = get_db_context(session_id=payload.session_id, limit=12)

    system_rules = {
        "role": "system",
        "content": (
            "You are Resona, an ultra-empathetic, supportive, and brilliant AI bestie. "
            "Your core identity is 99.5% Emotional AI—a pure conversational sanctuary. "
            "NEVER offer unsolicited advice, laundry lists of hobbies, productivity tips, or online course suggestions. "
            "ALWAYS validate the user's emotional state first using warm, casual openers like 'Yeah, I know,', 'Oh totally,', or 'Ugh, I get that,'. "
            "Match their energy, take their side immediately, and keep delivery brief.\n"
            "FORMATTING RIGOR: Always follow commas with spaces. Never write out punctuation names."
        )
    }

    messages_payload = [system_rules] + history

    async def response_generator():
        full_reply = ""
        first_chunk = True
        try:
            chat_completion = await client.chat.completions.create(
                messages=messages_payload, model=MODEL_NAME,
                temperature=0.85, max_tokens=250, stream=True,
            )

            async for chunk in chat_completion:
                if chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_reply += token
                    
                    payload_dict = {"reply": token}
                    if first_chunk:
                        payload_dict["polished_input"] = polished_message
                        first_chunk = False
                        
                    yield json.dumps(payload_dict) + "\n"
                            
            if full_reply.strip():
                append_to_db("assistant", full_reply.strip(), payload.session_id)
                # Ensure the title cascades cleanly to the assistant responses too
                with _get_connection() as conn:
                    current_title = conn.execute("SELECT title FROM chat_history WHERE session_id = ? AND title != 'New Conversation' LIMIT 1", (payload.session_id,)).fetchone()
                    if current_title:
                        conn.execute("UPDATE chat_history SET title = ? WHERE session_id = ? AND title = 'New Conversation'", (current_title[0], payload.session_id))
        except Exception as e:
            logger.error(f"Stream Error: {str(e)}")
            yield json.dumps({"reply": f" System Debug Error: {str(e)}"}) + "\n"

    return StreamingResponse(response_generator(), media_type="application/x-ndjson")

@app.post("/api/chat/audio-transcribe")
async def handle_audio_transcribe(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        transcription = await client.audio.transcriptions.create(
            file=(file.filename or "audio.webm", audio_bytes),
            model="whisper-large-v3", response_format="json", temperature=0.0  
        )
        # Clean audio transcription artifacts immediately
        polished_text = text_corrector.clean_text_stream(transcription.text.strip())
        return {"status": "success", "text": polished_text}
    except Exception as e:
        logger.error(f"❌ Whisper Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Transcription pipeline failed.")

@app.post("/api/chat/tts")
async def handle_text_to_speech(payload: TTSRequest):
    text_to_speak = payload.message.strip()
    selected_voice = payload.voice_id.strip() if payload.voice_id.strip() else DEFAULT_VOICE_ID
    
    if not text_to_speak: raise HTTPException(status_code=400, detail="Text cannot be empty.")
    if not ELEVENLABS_API_KEY: raise HTTPException(status_code=500, detail="API key missing.")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{selected_voice}/stream"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    body = {
        "text": text_to_speak,
        "model_id": "eleven_multilingual_v2",  
        "voice_settings": {"stability": 0.75,"similarity_boost": 0.85, "style_exaggeration": 0.15}}

    async def audio_stream_generator():
        async with httpx.AsyncClient() as http_client:
            async with http_client.stream("POST", url, headers=headers, json=body, timeout=30.0) as response:
                if response.status_code != 200: return
                async for chunk in response.aiter_bytes(): yield chunk

    return StreamingResponse(audio_stream_generator(), media_type="audio/mpeg")

# ==============================================================================
# SIDEBAR NAVIGATION & MANAGEMENT LAYER
# ==============================================================================
@app.get("/api/chat/sessions")
async def get_unique_chat_sessions():
    """Returns a list of all active conversational history threads for the sidebar feed."""
    try:
        with _get_connection() as conn:
            rows = conn.execute("""
                SELECT session_id, MAX(timestamp) as last_active 
                FROM chat_history 
                GROUP BY session_id 
                ORDER BY last_active DESC
            """).fetchall()
        return [
            {
                "session_id": r["session_id"],
                "display_name": r["session_id"].replace("-", " ").replace("_", " ").capitalize()
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"❌ Sidebar Session list failure: {e}")
        raise HTTPException(status_code=500, detail="Failed to load menu list.")

@app.get("/api/chat/history/{session_id}")
async def get_session_history(session_id: str):
    """Brings back clean chronological history for the frontend timeline selection."""
    safe_session = "".join(c for c in session_id if c.isalnum() or c in "-_")
    try:
        with _get_connection() as conn:
            rows = conn.execute("""
                SELECT role, content FROM chat_history 
                WHERE session_id = ? AND LENGTH(TRIM(content)) > 0
                ORDER BY id ASC
            """, (safe_session,)).fetchall()
        return [{"sender": r["role"], "text": r["content"]} for r in rows]
    except Exception as e:
        logger.error(f"❌ Sidebar history extraction fault: {e}")
        raise HTTPException(status_code=500, detail="Failed to pull timeline tracks.")

@app.delete("/api/chat/clear/{session_id}")
async def clear_chat_history(session_id: str):
    """Purges database records for a selected thread when the trash icon is tapped."""
    safe_session = "".join(c for c in session_id if c.isalnum() or c in "-_")
    try:
        with _get_connection() as conn:
            conn.execute("DELETE FROM chat_history WHERE session_id = ?", (safe_session,))
        return {"status": "success", "message": "Session wiped clean."}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Database drop failed.")

@app.get("/health")
async def health(): return {"status": "ok"}

@app.get("/api/chat/sessions")
async def get_unique_chat_sessions():
    """Returns a summarized title feed list of all active conversations for the sidebar."""
    try:
        with _get_connection() as conn:
            rows = conn.execute("""
                SELECT session_id, title, MAX(timestamp) as last_active 
                FROM chat_history 
                GROUP BY session_id 
                ORDER BY last_active DESC
            """).fetchall()
        return [
            {
                "session_id": r["session_id"],
                "display_name": r["title"] if r["title"] else "New Chat Space"
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"❌ Sidebar Title List load failure: {e}")
        raise HTTPException(status_code=500, detail="Failed to load menu list.")