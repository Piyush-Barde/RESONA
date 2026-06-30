from database import get_connection
from config import client, MODEL_NAME, logger

def lookup_past_reference(user_message: str) -> str:
    words = user_message.lower().split()
    if not any(k in words for k in ["remember", "forgot", "idea", "person", "project", "guy", "stuff"]):
        return ""
        
    with get_connection() as conn:
        memories = conn.execute("""
            SELECT m.category, m.keyword, m.summary, s.title 
            FROM session_memory_indices m
            JOIN chat_sessions s ON m.session_id = s.session_id
        """).fetchall()
        
    matched_chunks = []
    for mem in memories:
        if mem["keyword"].lower() in user_message.lower():
            matched_chunks.append(
                f"• Reference Found [From Past Chat Space: '{mem['title']}']: "
                f"Regarding the {mem['category']} '{mem['keyword']}': {mem['summary']}"
            )
            
    if matched_chunks:
        logger.info(f"🧠 Found {len(matched_chunks)} contextual reference vectors.")
        return "\n".join(matched_chunks)
    return ""

async def extract_and_save_session_indices(session_id: str, history: list):
    if len(history) < 2: return
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in history[-4:])
    
    prompt = (
        "Analyze the snippet and extract any distinct proper nouns, project names, app ideas, or people discussed.\n\n"
        f"Transcript:\n{transcript}\n\n"
        "Return EXACTLY in this format:\n"
        "CATEGORY: idea/person/project/general\n"
        "KEYWORD: exact name\n"
        "SUMMARY: 1-sentence snapshot of stance\n"
        "Do not include any other markdown text."
    )
    
    try:
        response = await client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_NAME, temperature=0.1, max_tokens=80
        )
        content = response.choices[0].message.content.strip()
        
        result = {}
        for line in content.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                result[k.strip().upper()] = v.strip()
                
        if result.get("KEYWORD") and result.get("SUMMARY"):
            with get_connection() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM session_memory_indices WHERE session_id = ? AND keyword = ?",
                    (session_id, result["KEYWORD"])
                ).fetchone()
                if not exists:
                    conn.execute("""
                        INSERT INTO session_memory_indices (session_id, category, keyword, summary)
                        VALUES (?, ?, ?, ?)
                    """, (session_id, result.get("CATEGORY", "general").lower(), result["KEYWORD"], result["SUMMARY"]))
    except Exception as e:
        logger.error(f"Failed to capture context vectors: {e}")