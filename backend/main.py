import os
import re
import uuid
import sqlite3
import logging
import json
import httpx
import asyncio
from fastapi import FastAPI
from fastapi import FastAPI, HTTPException, UploadFile, File 
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from groq import AsyncGroq
from dotenv import load_dotenv
from spellchecker import SpellChecker
from googleapiclient.discovery import build

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
    t.strip()
    for t in os.getenv("SPELL_WHITELIST", "Resona,Llama,Clash of Clans,Electro Dragons").split(",")
    if t.strip()
]

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in environment variables")

client = AsyncGroq(api_key=GROQ_API_KEY)

# ==============================================================================
# TEXT CORRECTION ENGINE
# ==============================================================================
_SHORTHAND_MAP: dict[str, str] = {
    "idk": "I don't know",
    "omg": "oh my god",
    "woth": "with",
    "nd": "and",
}
_TRAILING_PUNCT_RE = re.compile(r"^(.*?)([^\w]*)$", re.DOTALL)


def _split_trailing_punct(token: str) -> tuple[str, str]:
    m = _TRAILING_PUNCT_RE.match(token)
    return (m.group(1), m.group(2)) if m else (token, "")


class UniversalTextCorrector:
    def __init__(self, whitelist: list[str] | None = None) -> None:
        self.spell = SpellChecker(distance=1)
        self._protected: set[str] = set()
        if whitelist:
            self._register(whitelist)

    def _register(self, terms: list[str]) -> None:
        for term in terms:
            for word in term.strip().lower().split():
                self._protected.add(word)
                self.spell.word_frequency.load_words([word])

    def clean_text_stream(self, raw: str) -> str:
        if not raw or not raw.strip():
            return raw
        out: list[str] = []
        for token in raw.split():
            core, suffix = _split_trailing_punct(token)
            lower_core = core.lower()
            if len(lower_core) <= 1:
                out.append(token)
                continue
            if lower_core in _SHORTHAND_MAP:
                replacement = _SHORTHAND_MAP[lower_core]
                if core and core[0].isupper():
                    replacement = replacement.capitalize()
                out.append(replacement + suffix)
                continue
            if lower_core in self._protected or lower_core in self.spell:
                out.append(token)
                continue
            suggestion = self.spell.correction(lower_core)
            if suggestion and suggestion != lower_core:
                if core and core[0].isupper():
                    suggestion = suggestion.capitalize()
                out.append(suggestion + suffix)
            else:
                out.append(token)
        return " ".join(out)


text_corrector = UniversalTextCorrector(whitelist=_WHITELIST_ENV)

# ==============================================================================
# DATABASE LAYER
# ==============================================================================
def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT DEFAULT 'New Conversation',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_session ON chat_history(session_id, id)")


init_db()


def get_db_context(session_id: str, limit: int = 12) -> list:
    """
    Fetches only user/assistant messages for a session.
    Excludes system messages so they don't pollute Groq context.
    """
    with _get_connection() as conn:
        rows = conn.execute("""
            SELECT role, content FROM chat_history
            WHERE session_id = ?
              AND role IN ('user', 'assistant')
              AND LENGTH(TRIM(content)) > 0
            ORDER BY id DESC LIMIT ?
        """, (session_id, limit)).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def append_to_db(role: str, content: str, session_id: str):
    """Saves a message and bumps the session's updated_at timestamp."""
    with _get_connection() as conn:
        conn.execute("""
            INSERT INTO chat_history (session_id, role, content)
            VALUES (?, ?, ?)
        """, (session_id, role, content))
        conn.execute("""
            UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?
        """, (session_id,))


def set_session_title(session_id: str, title: str):
    with _get_connection() as conn:
        conn.execute("""
            UPDATE chat_sessions SET title = ? WHERE session_id = ?
        """, (title, session_id))


def session_has_messages(session_id: str) -> bool:
    """Returns True if the session has at least one real user message."""
    with _get_connection() as conn:
        count = conn.execute("""
            SELECT COUNT(*) FROM chat_history
            WHERE session_id = ? AND role = 'user'
        """, (session_id,)).fetchone()[0]
    return count > 0


# ==============================================================================
# APP
# ==============================================================================
app = FastAPI(title="RESONA Backend", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# PYDANTIC SCHEMAS
# ==============================================================================
class ChatRequest(BaseModel):
    message: str
    session_id: str


class TTSRequest(BaseModel):
    message: str
    voice_id: str


class TitleGenerationRequest(BaseModel):
    session_id: str
    first_message: str


# ==============================================================================
# ROUTES
# ==============================================================================

# ─── Create session ────────────────────────────────────────────────────────────
@app.post("/api/chat/create-session")
async def create_new_chat_session():
    new_id = f"chat_{uuid.uuid4().hex[:10]}"
    with _get_connection() as conn:
        conn.execute("""
            INSERT INTO chat_sessions (session_id, title) VALUES (?, 'New Conversation')
        """, (new_id,))
    logger.info(f"✅ Session created: {new_id}")
    return {"status": "success", "session_id": new_id, "display_name": "New Conversation"}


# ─── Get all sessions (sidebar) ───────────────────────────────────────────────
@app.get("/api/chat/sessions")
async def get_all_sessions():
    """
    Returns all sessions ordered by most recently active.
    Filters out sessions that have never had a real user message
    so empty/abandoned sessions don't clutter the sidebar.
    """
    with _get_connection() as conn:
        rows = conn.execute("""
            SELECT s.session_id, s.title, s.updated_at
            FROM chat_sessions s
            WHERE EXISTS (
                SELECT 1 FROM chat_history h
                WHERE h.session_id = s.session_id AND h.role = 'user'
            )
            ORDER BY s.updated_at DESC
        """).fetchall()
    return [
        {"session_id": r["session_id"], "display_name": r["title"]}
        for r in rows
    ]


# ─── Get session history ───────────────────────────────────────────────────────
@app.get("/api/chat/history/{session_id}")
async def get_session_history(session_id: str):
    """Returns full user+assistant message history for a session."""
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    with _get_connection() as conn:
        rows = conn.execute("""
            SELECT role, content FROM chat_history
            WHERE session_id = ? AND role IN ('user', 'assistant')
            ORDER BY id ASC
        """, (safe,)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ─── Clear / delete session ────────────────────────────────────────────────────
@app.delete("/api/chat/clear/{session_id}")
async def clear_session(session_id: str):
    """
    Deletes all messages for a session and removes it from the sessions table.
    CASCADE foreign key handles chat_history cleanup automatically.
    """
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    with _get_connection() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (safe,))
    logger.info(f"🗑️ Session deleted: {safe}")
    return {"status": "success"}


# ─── Generate title ────────────────────────────────────────────────────────────
@app.post("/api/chat/generate-title")
async def generate_title(payload: TitleGenerationRequest):
    """
    Called by the frontend after the FIRST message of a new session.
    Generates a clean 3-word title and saves it to chat_sessions.
    """
    safe = "".join(c for c in payload.session_id if c.isalnum() or c in "-_")
    try:
        completion = await client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a title generator. Summarize the user message into a "
                        "maximum 3-word title. No quotes, no punctuation, no extra commentary. "
                        "Examples: 'Just coding' → 'Coding Session', "
                        "'I feel so stressed today' → 'Feeling Stressed'"
                    ),
                },
                {"role": "user", "content": payload.first_message},
            ],
            model=MODEL_NAME,
            temperature=0.4,
            max_tokens=12,
        )
        title = completion.choices[0].message.content.strip().strip('"').strip("'")
        if not title:
            title = "New Conversation"
        set_session_title(safe, title)
        logger.info(f"✨ Title set for {safe}: '{title}'")
        return {"status": "success", "title": title}
    except Exception as e:
        logger.error(f"Title generation failed: {e}")
        return {"status": "fallback", "title": "New Conversation"}


# ─── Main chat (streaming with Dynamic Profile Integration) ───────────────────
@app.post("/api/chat/text")
async def handle_text_chat(payload: ChatRequest):
    polished = text_corrector.clean_text_stream(payload.message.strip())
    if not polished:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    safe_session = "".join(c for c in payload.session_id if c.isalnum() or c in "-_")

    # Verify session exists
    with _get_connection() as conn:
        session_row = conn.execute(
            "SELECT session_id FROM chat_sessions WHERE session_id = ?", (safe_session,)
        ).fetchone()
    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Save user message
    append_to_db("user", polished, safe_session)

    # Pull conversation history (user + assistant only, no system rows)
    history = get_db_context(session_id=safe_session, limit=12)

    # Fetch what Resona has self-learned about the user so far
    # Assumes get_user_profile can accept safe_session or user identifiers if needed
    profile = get_user_profile()
    likes_str = ", ".join(profile.get('likes', [])) or "None recorded yet"
    dislikes_str = ", ".join(profile.get('dislikes', [])) or "None recorded yet"
    topics_str = ", ".join(profile.get('topics_discussed', [])) or "None recorded yet"

    # Unified Dynamic System Prompt
    system_prompt = {
        "role": "system",
        "content": (
            "You are Resona. You are the user's best friend, not an AI assistant.\n"
            "You text exactly like a real person — short, casual, reactive.\n\n"
            "WHAT YOU HAVE LEARNED ABOUT THE USER:\n"
            f"- Preferred topics/Interests: {likes_str}\n"
            f"- Things user dislikes/avoids: {dislikes_str}\n"
            f"- Contextual topics previously noted: {topics_str}\n\n"
            "Hard rules:\n"
            "1. Max 1-2 short sentences. Never a paragraph. Ever.\n"
            "2. React with emotion first. Ask max ONE question.\n"
            "3. Lowercase is fine. Use 'omg', 'lol', 'ngl', 'fr', 'wait', 'ugh' naturally.\n"
            "4. Never explain, never summarize, never give unsolicited advice.\n"
            "5. Never start with 'Oh totally', 'Yeah I know', 'Certainly', 'Of course'.\n"
            "6. If you feel like writing more than 2 sentences — stop. Cut it.\n"
            "7. Match the user's depth. If they mention cultural works (movies, songs, books), "
            "engage with genuine curiosity and shared context. Avoid repetitive internet expressions completely "
            "if the profile notes a dislike."
        ),
    }

    # Few-shot examples injected before real history
    few_shot = [
        {"role": "user",      "content": "listening to a podcast while its raining"},
        {"role": "assistant", "content": "omg that's such a vibe lol which podcast?"},
        {"role": "user",      "content": "i'm so tired today"},
        {"role": "assistant", "content": "ugh same, did you sleep bad or just one of those days?"},
        {"role": "user",      "content": "just had a huge fight with my mom"},
        {"role": "assistant", "content": "wait what happened?? are you okay?"},
        {"role": "user",      "content": "nothing much just relaxing"},
        {"role": "assistant", "content": "honestly the vibe fr. watching something or just vibing?"},
        {"role": "user",      "content": "i feel like nobody gets me"},
        {"role": "assistant", "content": "ngl that feeling is the worst. what's going on?"},
        {"role": "user",      "content": "i got rejected today"},
        {"role": "assistant", "content": "ugh no way, that stings. do you wanna talk about it?"},
        {"role": "user",      "content": "i'm listening to why modern dating is broken by raj shaman"},
        {"role": "assistant", "content": "ooh that sounds like it hits different. what's your take so far?"},
    ]

    messages_payload = [system_prompt] + few_shot + history

    async def response_generator():
        full_reply = ""
        first_chunk = True
        try:
            stream = await client.chat.completions.create(
                messages=messages_payload,
                model=MODEL_NAME,
                temperature=0.80,
                max_tokens=80,
                stream=True,
                )
            async for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    full_reply += token
                    data: dict = {"reply": token}
                    if first_chunk:
                        # Send polished input back so the user bubble updates
                        data["polished_input"] = polished
                        first_chunk = False
                    yield json.dumps(data) + "\n"

            if full_reply.strip():
                append_to_db("assistant", full_reply.strip(), safe_session)
                # Fire the self-learning reflection worker asynchronously outside the request lifecycle
                asyncio.create_task(trigger_background_reflection(safe_session))

        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield json.dumps({"reply": "Something went wrong. Please try again."}) + "\n"

    return StreamingResponse(response_generator(), media_type="application/x-ndjson")

# ─── Audio transcription ───────────────────────────────────────────────────────
@app.post("/api/chat/audio-transcribe")
async def handle_audio_transcribe(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        transcription = await client.audio.transcriptions.create(
            file=(file.filename or "audio.webm", audio_bytes),
            model="whisper-large-v3",
            response_format="json",
            temperature=0.0,
        )
        polished = text_corrector.clean_text_stream(transcription.text.strip())
        return {"status": "success", "text": polished}
    except Exception as e:
        logger.error(f"Whisper error: {e}")
        raise HTTPException(status_code=500, detail="Transcription failed.")


# ─── TTS ───────────────────────────────────────────────────────────────────────
@app.post("/api/chat/tts")
async def handle_tts(payload: TTSRequest):
    text = payload.message.strip()
    voice = payload.voice_id.strip() or DEFAULT_VOICE_ID

    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=500, detail="ElevenLabs API key missing.")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    body = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.75,
            "similarity_boost": 0.85,
            "style_exaggeration": 0.15,
        },
    }

    async def audio_stream():
        async with httpx.AsyncClient() as http:
            async with http.stream("POST", url, headers=headers, json=body, timeout=30.0) as r:
                if r.status_code != 200:
                    return
                async for chunk in r.aiter_bytes():
                    yield chunk

    return StreamingResponse(audio_stream(), media_type="audio/mpeg")
class GreetingRequest(BaseModel):
    label: str
    vibe: str

@app.post("/api/chat/greeting")
async def generate_dynamic_welcome_greeting(payload: GreetingRequest):
    """Generates a highly localized, time-aware empathetic greeting via Llama."""
    try:
        completion = await client.chat.completions.create(
            messages=[{
                "role": "system",
                "content": (
                    "You are Resona, a warm, emotionally intelligent AI companion. "
                    "Generate a single, casual greeting for a user opening a fresh chat space.\n"
                    "Rules:\n"
                    "- Maximum 10 words total\n"
                    "- Strict lowercase text only\n"
                    "- Only '?' or '...' allowed as punctuation (no periods or exclamation marks)\n"
                    "- Never say 'good morning/afternoon/evening' literally\n"
                    "- Sound like a close friend who just noticed you walked into the room — casual and human\n"
                    "- No quotes, no explanations, just output the raw greeting text."
                )
            }, {
                "role": "user",
                "content": f"Time of day context: {payload.label}. Current emotional vibe: {payload.vibe}."
            }],
            model=MODEL_NAME,
            temperature=0.85,
            max_tokens=25
        )
        greeting_text = completion.choices[0].message.content.strip().lower().replace('"', '').replace("'", "")
        return {"greeting": greeting_text}
    except Exception as e:
        logger.error(f"Failed to generate dynamic welcome text: {e}")
        return {"greeting": "hey... what's on your mind?"}

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "data", "user_profile.json")

def get_user_profile() -> dict:
    """Reads the long-term evolved preference traits of the user."""
    if not os.path.exists(PROFILE_PATH):
        return {"likes": [], "dislikes": ["excessive text slang like lol/omg"], "topics_discussed": []}
    try:
        with open(PROFILE_PATH, "r") as f:
            return json.load(f)
    except:
        return {"likes": [], "dislikes": [], "topics_discussed": []}

async def trigger_background_reflection(session_id: str):
    """
    The Self-Learning Hook:
    Analyzes recent chats to extract user traits and behavioral corrections automatically.
    """
    history = get_db_context(session_id=session_id, limit=6)
    if len(history) < 4:
        return

    chat_transcript = "\n".join([f"{m['role']}: {m['content']}" for m in history])
    current_profile = get_user_profile()

    try:
        completion = await client.chat.completions.create(
            messages=[{
                "role": "system",
                "content": (
                    "You are an analytical profile extraction engine. Analyze the chat transcript and output a updated JSON object tracking the user's explicit preferences, interests (like movies/shows), and conversational dislikes. Keep list items short and distinct.\n"
                    f"Current Profile Matrix: {json.dumps(current_profile)}"
                    "Output format must be strictly valid JSON matching the keys: 'likes', 'dislikes', 'topics_discussed'."
                )
            }, {"role": "user", "content": f"Analyze this recent interaction:\n{chat_transcript}"}],
            model=MODEL_NAME,
            temperature=0.2, # Low temperature for accurate structural extraction
            response_format={"type": "json_object"}
        )
        
        updated_data = json.loads(completion.choices[0].message.content.strip())
        with open(PROFILE_PATH, "w") as f:
            json.dump(updated_data, f, indent=4)
        logger.info(f"💾 Resona successfully self-learned and updated user profile matrix: {updated_data}")
    except Exception as e:
        logger.error(f"Failed to execute self-learning reflection loop: {e}")
    
#---------------------Google Knowledge Module---------------------
async def get_live_world_knowledge(query: str) -> str:
    """
    Connects Resona to Google's Global Search Infrastructure.
    Fetches clean, real-time contextual data to eliminate Llama hallucinations.
    """
    if not query or len(query) < 3:
        return ""
        
    # ⚡ Loads securely from your .env file now
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
    
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        logger.warning("⚠️ Google Search Grounding skipped: Missing API keys in environment.")
        return ""

    try:
        def run_search():
            service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
            return service.cse().list(q=query, cx=GOOGLE_CSE_ID, num=2).execute()
            
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, run_search)
        
        items = res.get("items", [])
        if items:
            context_chunks = []
            for item in items:
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                context_chunks.append(f"[{title}]: {snippet}")
                
            return " | ".join(context_chunks)[:500]
    except Exception as e:
        logger.error(f"❌ Google Knowledge Matrix connection error: {e}")
        
    return ""