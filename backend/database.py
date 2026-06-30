import os
import sqlite3
import json
from config import DB_PATH, PROFILE_PATH

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                title      TEXT     DEFAULT 'New Conversation',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id         INTEGER  PRIMARY KEY AUTOINCREMENT,
                session_id TEXT     NOT NULL,
                role       TEXT     NOT NULL,
                content    TEXT     NOT NULL,
                timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_memory_indices (
                id         INTEGER  PRIMARY KEY AUTOINCREMENT,
                session_id TEXT     NOT NULL,
                category   TEXT     NOT NULL,
                keyword    TEXT     NOT NULL,
                summary    TEXT     NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_session ON chat_history(session_id, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_keyword ON session_memory_indices(keyword)")

def get_db_context(session_id: str, limit: int = 12) -> list:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT role, content FROM chat_history WHERE session_id = ? AND role IN ('user', 'assistant')
            AND LENGTH(TRIM(content)) > 0 ORDER BY id DESC LIMIT ?
        """, (session_id, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

def append_to_db(role: str, content: str, session_id: str):
    with get_connection() as conn:
        conn.execute("INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)", (session_id, role, content))
        conn.execute("UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?", (session_id,))

def set_session_title(session_id: str, title: str):
    with get_connection() as conn:
        conn.execute("UPDATE chat_sessions SET title = ? WHERE session_id = ?", (title, session_id))

def get_user_profile() -> dict:
    default = {"likes": [], "dislikes": [], "topics_discussed": []}
    if not os.path.exists(PROFILE_PATH): return default
    try:
        with open(PROFILE_PATH, "r") as f: return json.load(f)
    except Exception: return default