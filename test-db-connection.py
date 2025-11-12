#!/usr/bin/env python3
import psycopg2
import sys
from urllib.parse import quote

# Test different password encodings
password_raw = "Sunnyday8?!"
password_encoded = "Sunnyday8%3F%21"
username = "VericaseDocsAdmin"
host = "database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com"
database = "postgres"

print("Testing RDS Database Connection")
print("=" * 50)

# Test 1: URL-encoded password
print("\nTest 1: Using URL-encoded password in connection string")
try:
    url1 = f"postgresql://{username}:{password_encoded}@{host}:5432/{database}"
    print(f"URL: {url1}")
    conn1 = psycopg2.connect(url1)
    print("✓ SUCCESS with URL-encoded password!")
    conn1.close()
except Exception as e:
    print(f"✗ FAILED: {e}")

# Test 2: Raw password
print("\nTest 2: Using raw password parameters")
try:
    conn2 = psycopg2.connect(
        host=host,
        database=database,
        user=username,
        password=password_raw,
        port=5432
    )
    print("✓ SUCCESS with raw password!")
    conn2.close()
except Exception as e:
    print(f"✗ FAILED: {e}")

# Test 3: Python URL encoding
print("\nTest 3: Using Python URL encoding")
try:
    password_py_encoded = quote(password_raw, safe='')
    url3 = f"postgresql://{username}:{password_py_encoded}@{host}:5432/{database}"
    print(f"Python encoded: {password_py_encoded}")
    print(f"URL: {url3}")
    conn3 = psycopg2.connect(url3)
    print("✓ SUCCESS with Python URL encoding!")
    conn3.close()
except Exception as e:
    print(f"✗ FAILED: {e}")

print("\n" + "=" * 50)
print("Recommendation: Use the encoding that works above in apprunner.yaml")
