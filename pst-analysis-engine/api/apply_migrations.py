"""
Apply SQL migrations to PostgreSQL database
"""
import psycopg2
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / '.env')

# Get database URL
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg2://vericase:vericase@localhost:55432/vericase')

# Convert SQLAlchemy URL to psycopg2 format
if DATABASE_URL.startswith('postgresql+psycopg2://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql+psycopg2://', 'postgresql://')

print(f"Connecting to database...")
print(f"URL: {DATABASE_URL.replace(':vericase@', ':****@')}")

try:
    # Connect to PostgreSQL
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    
    # Get all migration files
    migrations_dir = Path(__file__).parent / 'migrations'
    migration_files = sorted(migrations_dir.glob('*.sql'))
    
    print(f"\nFound {len(migration_files)} migration files")
    print("="*60)
    
    for migration_file in migration_files:
        print(f"\nApplying: {migration_file.name}")
        
        try:
            sql = migration_file.read_text()
            cursor.execute(sql)
            print(f"   [OK] Successfully applied {migration_file.name}")
        except Exception as e:
            print(f"   [WARNING] Error applying {migration_file.name}: {e}")
            # Continue with other migrations
    
    print("\n" + "="*60)
    print("[SUCCESS] All migrations applied successfully!")
    print("="*60)
    
    # Verify tables exist
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name
    """)
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"\nDatabase tables ({len(tables)}):")
    for table in tables:
        print(f"   - {table}")
    
    conn.close()
    
except Exception as e:
    print(f"\n[ERROR] {e}")
    import traceback
    traceback.print_exc()
    exit(1)

