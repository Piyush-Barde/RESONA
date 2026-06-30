from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from config import text_corrector, client, MODEL_NAME
from database import init_db, get_connection, set_session_title
from chat_engine import stream_chat_response
from speech import process_audio_transcription, generate_tts_stream

init_db()

app = FastAPI(title="RESONA Backend", version="7.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message:    str
    session_id: str

class TTSRequest(BaseModel):
    message:  str
    voice_id: str

class TitleGenerationRequest(BaseModel):
    session_id:    str
    first_message: str

class GreetingRequest(BaseModel):
    label: str
    vibe:  str

@app.post("/api/chat/create-session")
async def create_new_chat_session():
    import uuid
    new_id = f"chat_{uuid.uuid4().hex[:10]}"
    with get_connection() as conn:
        conn.execute("INSERT INTO chat_sessions (session_id, title) VALUES (?, 'New Conversation')", (new_id,))
    return {"status": "success", "session_id": new_id, "display_name": "New Conversation"}

@app.get("/api/chat/sessions")
async def get_all_sessions():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT s.session_id, s.title FROM chat_sessions s
            WHERE EXISTS (SELECT 1 FROM chat_history h WHERE h.session_id = s.session_id AND h.role = 'user')
            ORDER BY s.created_at DESC
        """).fetchall()
    return [{"session_id": r["session_id"], "display_name": r["title"]} for r in rows]

@app.get("/api/chat/history/{session_id}")
async def get_session_history(session_id: str):
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    with get_connection() as conn:
        rows = conn.execute("SELECT role, content FROM chat_history WHERE session_id = ? AND role IN ('user', 'assistant') ORDER BY id ASC", (safe,)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]

@app.delete("/api/chat/clear/{session_id}")
async def clear_session(session_id: str):
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    with get_connection() as conn: conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (safe,))
    return {"status": "success"}

@app.post("/api/chat/generate-title")
async def generate_title(payload: TitleGenerationRequest):
    safe = "".join(c for c in payload.session_id if c.isalnum() or c in "-_")
    try:
        completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Summarize user message into max 3 words. No quotes."},
                {"role": "user", "content": payload.first_message},
            ],
            model=MODEL_NAME, temperature=0.4, max_tokens=12,
        )
        title = completion.choices[0].message.content.strip().strip('"').strip("'") or "New Conversation"
        set_session_title(safe, title)
        return {"status": "success", "title": title}
    except Exception:
        return {"status": "fallback", "title": "New Conversation"}

@app.post("/api/chat/text")
async def handle_text_chat(payload: ChatRequest):
    safe_session = "".join(c for c in payload.session_id if c.isalnum() or c in "-_")
    with get_connection() as conn:
        row = conn.execute("SELECT session_id FROM chat_sessions WHERE session_id = ?", (safe_session,)).fetchone()
    if not row: raise HTTPException(status_code=404, detail="Session not found.")

    polished = text_corrector.clean_text_stream(payload.message.strip())
    if not polished: raise HTTPException(status_code=400, detail="Message cannot be empty.")

    return await stream_chat_response(polished, safe_session)

@app.post("/api/chat/audio-transcribe")
async def handle_audio_transcribe(file: UploadFile = File(...)):
    bytes_data = await file.read()
    text = await process_audio_transcription(bytes_data, file.filename)
    return {"status": "success", "text": text}

@app.post("/api/chat/tts")
async def handle_tts(payload: TTSRequest):
    text = payload.message.strip()
    if not text: raise HTTPException(status_code=400, detail="Text cannot be empty.")
    return generate_tts_stream(text, payload.voice_id)

@app.post("/api/chat/greeting")
async def generate_dynamic_welcome_greeting(payload: GreetingRequest):
    try:
        completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are Resona, a warm friend. Greeting under 10 words. Lowercase. Only '?' or '...' punctuation."},
                {"role": "user", "content": f"Time of day: {payload.label}. Emotional vibe: {payload.vibe}."}
            ],
            model=MODEL_NAME, temperature=0.85, max_tokens=25,
        )
        text = completion.choices[0].message.content.strip().lower().replace('"', "").replace("'", "")
        return {"greeting": text}
    except Exception:
        return {"greeting": "hey... what's on your mind?"}