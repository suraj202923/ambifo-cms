import psycopg2

conn = psycopg2.connect(
    host="localhost", port=5432, dbname="ambifo_crm",
    user="postgres", password="Amla@123"
)
cur = conn.cursor()
cur.execute("ALTER TABLE email_logs ADD COLUMN IF NOT EXISTS recipient_email VARCHAR(255);")
conn.commit()
cur.close()
conn.close()
print("Migration done: recipient_email column added to email_logs.")
