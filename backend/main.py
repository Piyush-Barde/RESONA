import os
import sqlite3
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

# ==============================================================================
# LOGGING & CONFIGURATION
# ==============================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RESONA_BACKEND")

app = FastAPI(
    title="RESONA Real-Time Emotional Intelligence Engine",
    description="FastAPI gateway with SQLite relational database persistence.",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "resona"

# Define your SQL database location
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "resona.db")

# ==============================================================================
# SQLITE DATABASE INTERFACE LAYER
# ==============================================================================
def init_db():
    """Initializes the database and establishes the unified chat history schema."""
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
    logger.info("💾 SQLite Database Engine Initialized Successfully.")

# Run database setup immediately on boot
init_db()

def get_db_context(limit: int = 6) -> list:
    """Retrieves the recent historic chat window from the database table."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Fetch the last N rows matching the default active session
    cursor.execute("""
        SELECT role, content FROM chat_history 
        WHERE session_id = 'default_session' 
        ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    # Reverse them so they read chronologically down the timeline
    history = [{"role": row[0], "content": row[1]} for row in reversed(rows)]
    return history

def append_to_db(role: str, content: str):
    """Inserts an utterance record permanently into the SQLite engine layout."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chat_history (session_id, role, content) 
        VALUES ('default_session', ?, ?)
    """, (role, content))
    conn.commit()
    conn.close()

# ==============================================================================
# SCHEMAS & ROUTES
# ==============================================================================
class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str

@app.get("/")
async def root_check():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM chat_history")
    count = cursor.fetchone()[0]
    conn.close()
    return {"status": "online", "engine": "RESONA Relational Core", "stored_db_records": count}


@app.post("/api/chat/text", response_model=ChatResponse)
async def handle_text_chat(payload: ChatRequest):
    user_prompt = payload.message.strip()
    
    if not user_prompt:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")
        
    logger.info(f"💬 DB Pipeline Processing Token: '{user_prompt}'")

    # 1. Commit user statement permanently to database row layout
    append_to_db("user", user_prompt)

    # 2. Re-extract contextual database slice for prompt assembly
    chat_context = get_db_context(limit=6)

    # Compile working ChatML prompt structure
    raw_prompt = (
        "<|im_start|>system\n"
        "You are Resona, an empathetic, highly supportive, and deeply human voice assistant. "
        "When someone shares a feeling, actively validate their emotions first in a short sentence, "
        "and then immediately ask a natural, open-ended follow-up question to invite them to share more. "
        "Keep the overall response conversational, brief, and warm. Do not give lists of advice. "
        "CRITICAL GROUNDING: You are an AI assistant. You do not experience weather, heat, cold, or days. "
        "Always focus the conversation immediately back onto the human user.\n"
        "<|im_end|>\n"
    )

    for turn in chat_context:
        raw_prompt += f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n"
    
    raw_prompt += "<|im_start|>assistant\n"

    ollama_payload = {
        "model": MODEL_NAME,
        "prompt": raw_prompt,
        "stream": False,
        "options": {
            "temperature": 0.5,
            "top_p": 0.85,
            "stop": ["<|im_end|>", "<|im_start|>", ">>>"]
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(OLLAMA_API_URL, json=ollama_payload)
            
            if response.status_code != 200:
                return ChatResponse(response="I'm adjusting my memory structures right now.")
                
            ollama_data = response.json()
            resona_reply = ollama_data.get("response", "").strip()
            
            # String cleaning sequence
            resona_reply = resona_reply.replace("<|im_start|>", "").replace("<|im_end|>", "")
            resona_reply = resona_reply.lstrip("> ").strip()
            
            if not resona_reply:
                resona_reply = "I'm checking in on you. What's on your mind right now?"
                
            # 3. Commit Resona's clean generated answer directly to database engine
            append_to_db("assistant", resona_reply)
            
            logger.info("💾 Transaction complete: Row successfully added to resona.db")
            return ChatResponse(response=resona_reply)

        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Ollama service unreachable.")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))