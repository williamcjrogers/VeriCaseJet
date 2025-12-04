import sys
sys.path.append('/code')
from app.db import engine
from sqlalchemy import text

def check_table(table_name):
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table_name}'"))
        print(f"--- {table_name} ---")
        for row in result:
            print(row)

# check_table('email_attachments')
check_table('pst_files')
check_table('documents')
