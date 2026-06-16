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