"""
migrate_v2.py — Run this ONCE to upgrade your existing resona.db
to the new two-table schema (chat_sessions + chat_history).

Safe to run multiple times — checks before altering anything.
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "resona.db")

print(f"🔄 Opening database at: {DB_PATH}")
if not os.path.exists(DB_PATH):
    print("ℹ️  No existing database found — the app will create a fresh one on first run.")
    exit(0)

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=OFF")   # disable during migration
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ── Check what tables already exist ──────────────────────────────────────────
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
existing_tables = {r["name"] for r in cur.fetchall()}
print(f"📋 Existing tables: {existing_tables}")

# ── Step 1: Create chat_sessions if missing ───────────────────────────────────
if "chat_sessions" not in existing_tables:
    print("⚡ Creating chat_sessions table...")
    cur.execute("""
        CREATE TABLE chat_sessions (
            session_id TEXT PRIMARY KEY,
            title TEXT DEFAULT 'New Conversation',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("✅ chat_sessions created.")
else:
    print("ℹ️  chat_sessions already exists.")

# ── Step 2: Migrate data from old chat_history into chat_sessions ─────────────
if "chat_history" in existing_tables:
    # Check if old table has a title column (old schema)
    cur.execute("PRAGMA table_info(chat_history)")
    old_cols = {r["name"] for r in cur.fetchall()}
    print(f"📋 Old chat_history columns: {old_cols}")

    if "title" in old_cols:
        print("⚡ Migrating session titles from old chat_history into chat_sessions...")
        # Pull distinct sessions + their titles from old table
        sessions = cur.execute("""
            SELECT session_id, title, MIN(timestamp) as created_at, MAX(timestamp) as updated_at
            FROM chat_history
            WHERE session_id != 'default_session'
            GROUP BY session_id
        """).fetchall()

        for s in sessions:
            title = s["title"] if s["title"] and s["title"] not in ("New Conversation", "Conversation space initiated.", "") else "New Conversation"
            cur.execute("""
                INSERT OR IGNORE INTO chat_sessions (session_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, (s["session_id"], title, s["created_at"], s["updated_at"]))
        print(f"✅ Migrated {len(sessions)} sessions into chat_sessions.")

    # ── Step 3: Rebuild chat_history without the title column ────────────────
    print("⚡ Rebuilding chat_history table (removing title column, adding FK)...")
    cur.execute("ALTER TABLE chat_history RENAME TO chat_history_old")
    cur.execute("""
        CREATE TABLE chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_history_session ON chat_history(session_id, id)")

    # Copy only real user/assistant rows, skip system placeholders
    cur.execute("""
        INSERT INTO chat_history (session_id, role, content, timestamp)
        SELECT session_id, role, content, timestamp
        FROM chat_history_old
        WHERE role IN ('user', 'assistant')
          AND content != 'Conversation space initiated.'
          AND LENGTH(TRIM(content)) > 0
          AND session_id != 'default_session'
    """)
    migrated = cur.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
    print(f"✅ Migrated {migrated} messages into new chat_history.")

    cur.execute("DROP TABLE chat_history_old")
    print("✅ Old chat_history_old dropped.")

else:
    print("ℹ️  No old chat_history found — fresh install, nothing to migrate.")

conn.execute("PRAGMA foreign_keys=ON")
conn.commit()
conn.close()

print("\n🎉 Migration complete! You can now start the app normally.")
print("   Run: uvicorn main:app --reload")