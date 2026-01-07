#!/usr/bin/env python3
"""Check email body content in database."""
import sys

sys.path.insert(0, "/code")

from app.db import SessionLocal
from app.models import EmailMessage
from sqlalchemy import func

db = SessionLocal()

# Get a sample email with body content
email = (
    db.query(EmailMessage)
    .filter(EmailMessage.body_text.isnot(None))
    .filter(func.length(EmailMessage.body_text) > 100)
    .first()
)

if email:
    print("=== EMAIL ID:", email.id)
    print("=== SUBJECT:", repr(email.subject[:80]) if email.subject else None)
    print()
    print("=== BODY_TEXT (first 500 chars):")
    print(repr(email.body_text[:500]) if email.body_text else "None")
    print()
    print("=== BODY_TEXT_CLEAN (first 500 chars):")
    print(repr(email.body_text_clean[:500]) if email.body_text_clean else "None")
    print()
    print("=== BODY_HTML length:", len(email.body_html) if email.body_html else 0)
else:
    print("No email with body_text found")
db.close()
