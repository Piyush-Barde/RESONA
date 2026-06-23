import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "resona.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("SELECT * FROM chat_history")
rows = cursor.fetchall()

print(f"\n📊 TOTAL RECORD COUNT: {len(rows)}")
print("--- DATABASE ROWS LOADED ---")
for row in rows:
    print(row)

conn.close()
@app.get("/api/chat/history/{session_id}")
async def get_session_history(session_id: str):
    """Fetches full chat history for a clicked sidebar session thread."""
    safe_session = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return get_db_context(session_id=safe_session, limit=20)