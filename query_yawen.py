import psycopg2

conn = psycopg2.connect(
    host="localhost",
    database="vericase",
    user="vericase",
    password="vericase",
    port=54321
)

cur = conn.cursor()
cur.execute("SELECT id, filename, processing_status, error_message, total_emails FROM pst_files WHERE filename = 'Yawen.pst';")
rows = cur.fetchall()

if rows:
    for row in rows:
        print(f"ID: {row[0]}")
        print(f"Filename: {row[1]}")
        print(f"Status: {row[2]}")
        print(f"Error: {row[3]}")
        print(f"Total Emails: {row[4]}")
else:
    print("No records found for Yawen.pst")

cur.close()
conn.close()
