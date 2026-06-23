import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "resona.db")

print(f"🔄 Opening database at: {DB_PATH}")
if not os.path.exists(DB_PATH):
    print("❌ No existing database found to migrate. Make sure your pathing matches!")
    exit()

try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if column already exists to prevent crashes
    cursor.execute("PRAGMA table_info(chat_history)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "title" not in columns:
        print("⚡ Column 'title' is missing. Executing structural schema patch...")
        cursor.execute("ALTER TABLE chat_history ADD COLUMN title TEXT DEFAULT 'New Conversation'")
        conn.commit()
        print("✅ Migration successful! The 'title' column has been safely added.")
    else:
        print("ℹ️ The 'title' column already exists in your table structural schema.")
        
    conn.close()
except Exception as err:
    print(f"❌ Migration failed: {err}")