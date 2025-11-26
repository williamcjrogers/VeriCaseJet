#!/usr/bin/env pwsh
# Reset Database Script - Wipes all data and recreates fresh schema
# Works with both SQLite and PostgreSQL

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  VeriCase Database Reset Tool" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "WARNING: This will DELETE ALL data in your database!" -ForegroundColor Red
Write-Host ""

$confirmation = Read-Host "Are you sure you want to continue? Type 'YES' to proceed"
if ($confirmation -ne "YES") {
    Write-Host "Operation cancelled." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Starting database reset..." -ForegroundColor Green
Write-Host ""

# Store the current location
$originalLocation = Get-Location

try {
    # Navigate to the pst-analysis-engine directory
    Set-Location $PSScriptRoot

    # 1. Delete SQLite database file
    $sqliteDb = "vericase.db"
    if (Test-Path $sqliteDb) {
        Write-Host "[1/5] Removing SQLite database file..." -ForegroundColor Yellow
        Remove-Item $sqliteDb -Force
        Write-Host "      ✓ Deleted: $sqliteDb" -ForegroundColor Green
    } else {
        Write-Host "[1/5] No SQLite database found (skipping)" -ForegroundColor Gray
    }

    # 2. Clean up upload directories (optional - comment out if you want to keep files)
    Write-Host ""
    Write-Host "[2/5] Cleaning upload directories..." -ForegroundColor Yellow
    
    $uploadDirs = @("uploads", "data")
    foreach ($dir in $uploadDirs) {
        if (Test-Path $dir) {
            Get-ChildItem -Path $dir -Recurse | Remove-Item -Force -Recurse -ErrorAction SilentlyContinue
            Write-Host "      ✓ Cleaned: $dir" -ForegroundColor Green
        }
    }

    # 3. Check for PostgreSQL database
    Write-Host ""
    Write-Host "[3/5] Checking for PostgreSQL database..." -ForegroundColor Yellow
    
    # Load .env file if it exists
    $envFile = Join-Path $PSScriptRoot ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^([^=]+)=(.*)$') {
                $key = $matches[1].Trim()
                $value = $matches[2].Trim()
                if ($key -eq "DATABASE_URL") {
                    $env:DATABASE_URL = $value
                }
            }
        }
    }

    if ($env:DATABASE_URL) {
        if ($env:DATABASE_URL -like "*sqlite*") {
            Write-Host "      Using SQLite - already handled" -ForegroundColor Gray
        } elseif ($env:DATABASE_URL -like "*postgres*") {
            Write-Host "      PostgreSQL detected" -ForegroundColor Cyan
            Write-Host "      Attempting to reset PostgreSQL database..." -ForegroundColor Yellow
            
            # Try to run Python script to drop and recreate tables
            python -c @"
import psycopg2
import os
import sys

DATABASE_URL = os.getenv('DATABASE_URL', '')
if not DATABASE_URL:
    print('      No DATABASE_URL found')
    sys.exit(0)

# Convert SQLAlchemy URL to psycopg2 format
if DATABASE_URL.startswith('postgresql+psycopg2://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql+psycopg2://', 'postgresql://')

try:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute('''
        SELECT tablename FROM pg_tables 
        WHERE schemaname = 'public'
    ''')
    tables = [row[0] for row in cursor.fetchall()]
    
    # Drop all tables
    if tables:
        print(f'      Dropping {len(tables)} tables...')
        for table in tables:
            cursor.execute(f'DROP TABLE IF EXISTS {table} CASCADE')
        print('      ✓ All tables dropped')
    
    conn.close()
    print('      ✓ PostgreSQL reset complete')
except Exception as e:
    print(f'      Warning: Could not reset PostgreSQL: {e}')
"@
        }
    } else {
        Write-Host "      No DATABASE_URL configured" -ForegroundColor Gray
    }

    # 4. Recreate fresh schema
    Write-Host ""
    Write-Host "[4/5] Recreating fresh database schema..." -ForegroundColor Yellow
    
    # Check if we should use PostgreSQL or SQLite
    if ($env:DATABASE_URL -and $env:DATABASE_URL -like "*postgres*") {
        Write-Host "      Applying PostgreSQL migrations..." -ForegroundColor Cyan
        python api/apply_migrations.py
    } else {
        Write-Host "      Creating fresh SQLite database..." -ForegroundColor Cyan
        # The database will be auto-created on first run
        # But we can initialize it with the schema
        python -c @"
from pathlib import Path
import sqlite3

db_path = Path('vericase.db')
conn = sqlite3.connect(str(db_path))
print(f'      ✓ Created SQLite database: {db_path}')
conn.close()
"@
    }

    # 5. Create default admin user
    Write-Host ""
    Write-Host "[5/5] Creating default admin user..." -ForegroundColor Yellow
    
    python api/create_admin.py 2>&1 | ForEach-Object {
        if ($_ -match "Admin user created" -or $_ -match "already exists") {
            Write-Host "      ✓ $_" -ForegroundColor Green
        } else {
            Write-Host "      $_" -ForegroundColor Gray
        }
    }

    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  Database Reset Complete!" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  1. Start the API server: cd api && uvicorn app.main:app --reload" -ForegroundColor White
    Write-Host "  2. Login with default credentials (check create_admin.py output)" -ForegroundColor White
    Write-Host ""

} catch {
    Write-Host ""
    Write-Host "Error: $_" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
} finally {
    # Return to original location
    Set-Location $originalLocation
}


