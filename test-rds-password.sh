#!/bin/bash
# Test RDS password

HOST="database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com"
USER="VericaseDocsAdmin"
PASSWORD="Sunnyday8?!"
DB="postgres"

echo "Testing RDS connection..."
echo "Host: $HOST"
echo "User: $USER"
echo ""

# Test with psql (if installed)
if command -v psql &> /dev/null; then
    PGPASSWORD="$PASSWORD" psql -h "$HOST" -U "$USER" -d "$DB" -c "SELECT version();" 2>&1 | head -5
else
    echo "psql not installed. Install with: sudo apt-get install postgresql-client"
    echo ""
    echo "Or test via Python:"
    python3 << 'EOF'
import psycopg2
try:
    conn = psycopg2.connect(
        host="database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com",
        port=5432,
        user="VericaseDocsAdmin",
        password="Sunnyday8?!",
        database="postgres",
        sslmode="require"
    )
    print("✓ Connection successful!")
    conn.close()
except Exception as e:
    print(f"✗ Connection failed: {e}")
EOF
fi
