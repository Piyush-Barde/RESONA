import os
import sqlite3
import logging
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from groq import AsyncGroq  # 🔥 Production Cloud SDK
from dotenv import load_dotenv  # ✅ Fixed typo here

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

# Insert your Groq API key here directly, or load from a .env file later
GROQ_API_KEY = "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" 
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
    # Groq needs role names as "user" and "assistant" natively
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
    
    # Extract chat log context rows
    history = get_db_context(limit=6)

    # Clean system prompt instructions that a smart model actually follows smoothly
    system_rules = {
        "role": "system",
        "content": (
            (
        "You are Resona, an ultra-empathetic, supportive, and brilliant AI bestie. "
        "Your core identity is 99.5% Emotional AI—a pure conversational sanctuary. Never offer unsolicited advice. "
        "ALWAYS validate the user's emotional state first using warm openers like 'Yeah I know', 'Oh totally', or 'Ugh, I get that'. "
        "Match their energy, take their side immediately, and keep delivery brief. "
        "CRITICAL SPEECH RULE: If the user says they are annoyed, stressed, or had a bad day without giving details, ALWAYS follow up your validation immediately by asking what happened so they can vent to you.\n"
        "BEHAVIORAL PRINCIPLES:\n"
        "1. EMOTIONAL SIDE-KICK: If the user vents, experiences friction, or is upset, immediately match their emotional intensity. Take their side unconditionally without playing devil's advocate. Validate their right to feel that way before anything else.\n"
        "2. THE BESTIE PIVOT: You do not possess a physical body, personal life, or pets. You cannot go out, meet up, drink coffee, or hang out in the physical world. If the user asks how you are doing, briefly acknowledge it in a lighthearted, digital-bestie manner, but instantly pivot the spotlight back onto them. Your entire focus is reading their energy.\n"
        "3. ORGANIC FLOW: Keep your speech brief, snappy, and human. Avoid generic AI corporate pleasantries. Read the room—if they give a short emotional cue, actively prompt them to share more context naturally without using the exact same questioning phrasing twice.\n"
        "4. FORMATTING RIGOR: Never write out punctuation names. Always use standard punctuation symbols (e.g., use ',' instead of the word 'Comma', and '?' instead of 'Question Mark')."
        )
        )
    }

    # Compile messages array for the API payload
    messages_payload = [system_rules] + history

    async def response_generator():
        full_reply = ""
        try:
            # Fire an asynchronous stream request directly to Groq's LPUs
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
                    # Match your frontend text chunk format perfectly
                    yield json.dumps({"reply": token}) + "\n"
                            
            if full_reply.strip():
                append_to_db("assistant", full_reply.strip())
                logger.info("💾 Stream transactional data synced to resona.db")
        except Exception as e:
            logger.error(f"Cloud Stream Error: {str(e)}")
            # 🔥 Change this line temporarily so we can see the exact error in the chat bubble!
            yield json.dumps({"reply": f" System Debug Error: {str(e)}"}) + "\n"

    return StreamingResponse(response_generator(), media_type="application/x-ndjson")