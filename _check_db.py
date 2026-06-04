import os, urllib.parse, sys
from dotenv import load_dotenv
import psycopg2

load_dotenv()
url = os.environ["DATABASE_URL"]

parsed = urllib.parse.urlparse(url)
user = parsed.username
password = parsed.password
host = parsed.hostname
port = parsed.port
db = parsed.path.lstrip("/")

conn = psycopg2.connect(
    host=host, port=port, user=user, password=password, dbname=db,
    sslmode="require"
)
cur = conn.cursor()

print("=== USERS ===")
cur.execute("SELECT id, email, is_admin, ai_reply_enabled, pricing_tier FROM users")
for row in cur.fetchall():
    print(f"ID={row[0]} Email={row[1]} Admin={row[2]} AI={row[3]} Tier={row[4]}")

print("\n=== CONVERSATIONS (last 10) ===")
cur.execute("SELECT id, phone, message, category, channel, user_id, timestamp FROM conversations ORDER BY timestamp DESC LIMIT 10")
for row in cur.fetchall():
    msg = row[2][:60] if row[2] else ''
    print(f"ID={row[0]} Phone={row[1]} Msg={msg} Cat={row[3]} Chan={row[4]} UID={row[5]} Time={row[6]}")

print("\n=== PIPELINE LOGS (recent 5) ===")
cur.execute("SELECT id, message, category, success, errors, final_reply FROM pipeline_logs ORDER BY id DESC LIMIT 5")
for row in cur.fetchall():
    msg = row[1][:60] if row[1] else ''
    err = row[4][:80] if row[4] else ''
    reply = row[5][:60] if row[5] else ''
    print(f"ID={row[0]} Msg={msg} Cat={row[2]} OK={row[3]} Err={err} Reply={reply}")

print("\n=== PROMOTING ADMIN ===")
cur.execute("UPDATE users SET is_admin = TRUE WHERE email IN ('prevailfrancis@gmail.com', 'prevailfra@gmail.com')")
conn.commit()
print("Done")

cur.close()
conn.close()
