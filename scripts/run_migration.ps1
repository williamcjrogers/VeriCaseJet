# PowerShell script to run the non-email migration
$env:DATABASE_URL = "postgresql+psycopg2://vericase:vericase@localhost:54321/vericase"
python scripts/check_and_migrate_non_emails.py
