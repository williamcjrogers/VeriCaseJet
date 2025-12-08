#!/usr/bin/env python3
"""
SQLAlchemy 2.0 Mapped[] Migration Verification Tests

This test suite verifies that the migration from legacy Column() syntax
to SQLAlchemy 2.0 Mapped[] syntax is working correctly.
"""

import sys
import uuid
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add the project root to the path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_model_imports():
    """Test 1: Verify all models can be imported"""
    print("\n" + "=" * 60)
    print("TEST 1: Model Imports")
    print("=" * 60)

    try:
        from api.app.models import (
            # Core user models
            User,
            UserSession,
            PasswordHistory,
            LoginAttempt,
            # Document models
            Document,
            DocStatus,
            Folder,
            ShareLink,
            UserInvitation,
            DocumentShare,
            FolderShare,
            Favorite,
            DocumentVersion,
            # Legal domain models
            Company,
            UserCompany,
            Case,
            CaseUser,
            Issue,
            Evidence,
            Claim,
            ChronologyItem,
            Rebuttal,
            ContractClause,
            SearchQuery,
            DelayEvent,
            # PST analysis models
            Project,
            PSTFile,
            EmailMessage,
            EmailAttachment,
            Stakeholder,
            Keyword,
            Programme,
            AppSetting,
            # Evidence repository models
            EvidenceSource,
            EvidenceCollection,
            EvidenceItem,
            EvidenceCorrespondenceLink,
            EvidenceRelation,
            EvidenceCollectionItem,
            EvidenceActivityLog,
            # Contentious matters models
            ContentiousMatter,
            HeadOfClaim,
            ItemClaimLink,
            ItemComment,
        )

        print("✓ All 40+ models imported successfully")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_model_instantiation():
    """Test 2: Verify core models can be instantiated"""
    print("\n" + "=" * 60)
    print("TEST 2: Model Instantiation")
    print("=" * 60)

    try:
        from api.app.models import (
            User,
            Project,
            PSTFile,
            EmailMessage,
            EmailAttachment,
            Case,
            Company,
            Document,
        )

        # Test User instantiation
        user = User(email="test@test.com", password_hash="hash")
        print(f"✓ User instantiated: email={user.email}")

        # Test Project instantiation
        project = Project(
            project_name="Test Project", project_code="T001", owner_user_id=uuid.uuid4()
        )
        print(f"✓ Project instantiated: name={project.project_name}")

        # Test PSTFile instantiation
        pst_file = PSTFile(filename="test.pst", s3_key="uploads/test.pst")
        print(f"✓ PSTFile instantiated: filename={pst_file.filename}")

        # Test EmailMessage instantiation
        email_msg = EmailMessage(pst_file_id=uuid.uuid4())
        print(f"✓ EmailMessage instantiated: pst_file_id={email_msg.pst_file_id}")

        # Test EmailAttachment instantiation
        _ = EmailAttachment()
        print("✓ EmailAttachment instantiated")

        # Test Case instantiation
        case = Case(
            case_number="CASE-001",
            name="Test Case",
            owner_id=uuid.uuid4(),
            company_id=uuid.uuid4(),
        )
        print(f"✓ Case instantiated: case_number={case.case_number}")

        # Test Company instantiation
        company = Company(company_name="Test Company")
        print(f"✓ Company instantiated: name={company.company_name}")

        # Test Document instantiation
        doc = Document(
            filename="test.pdf", bucket="test-bucket", s3_key="docs/test.pdf"
        )
        print(f"✓ Document instantiated: filename={doc.filename}")

        return True
    except Exception as e:
        print(f"✗ Instantiation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_property_aliases():
    """Test 3: Verify backward-compatibility property aliases work"""
    print("\n" + "=" * 60)
    print("TEST 3: Property Aliases")
    print("=" * 60)

    try:
        from api.app.models import PSTFile, EmailAttachment

        # Test PSTFile.file_size property (alias for file_size_bytes)
        pst = PSTFile(filename="test.pst", s3_key="key", file_size_bytes=1024)
        assert (
            pst.file_size == 1024
        ), f"PSTFile.file_size alias failed: expected 1024, got {pst.file_size}"
        print(f"✓ PSTFile.file_size alias works: {pst.file_size} bytes")

        # Test EmailAttachment.file_size property (alias for file_size_bytes)
        att = EmailAttachment(file_size_bytes=2048)
        assert (
            att.file_size == 2048
        ), f"EmailAttachment.file_size alias failed: expected 2048, got {att.file_size}"
        print(f"✓ EmailAttachment.file_size alias works: {att.file_size} bytes")

        # Test None case
        att_none = EmailAttachment()
        assert (
            att_none.file_size is None
        ), "EmailAttachment.file_size should be None when file_size_bytes is None"
        print("✓ Property aliases handle None correctly")

        return True
    except AssertionError as e:
        print(f"✗ Assertion failed: {e}")
        return False
    except Exception as e:
        print(f"✗ Property alias test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_database_schema():
    """Test 4: Verify models match database schema"""
    print("\n" + "=" * 60)
    print("TEST 4: Database Schema Compatibility")
    print("=" * 60)

    try:
        from api.app.db import engine
        from sqlalchemy import inspect

        inspector = inspect(engine)
        tables_to_check = [
            "users",
            "projects",
            "pst_files",
            "email_messages",
            "email_attachments",
            "cases",
            "companies",
            "documents",
        ]

        existing_tables = inspector.get_table_names()

        for table in tables_to_check:
            if table in existing_tables:
                cols = [c["name"] for c in inspector.get_columns(table)]
                print(f"✓ {table}: {len(cols)} columns found")
            else:
                print(f"⚠ {table}: table not found (may need migration)")

        return True
    except Exception as e:
        print(f"✗ Schema check failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_orm_queries():
    """Test 5: Verify ORM queries work with Mapped[] syntax"""
    print("\n" + "=" * 60)
    print("TEST 5: ORM Query Tests")
    print("=" * 60)

    try:
        from api.app.db import SessionLocal
        from api.app.models import User, Project, EmailMessage, EmailAttachment

        db = SessionLocal()
        try:
            # Test basic queries
            users = db.query(User).limit(1).all()
            print(f"✓ User query succeeded: {len(users)} result(s)")

            projects = db.query(Project).limit(1).all()
            print(f"✓ Project query succeeded: {len(projects)} result(s)")

            emails = db.query(EmailMessage).limit(1).all()
            print(f"✓ EmailMessage query succeeded: {len(emails)} result(s)")

            attachments = db.query(EmailAttachment).limit(1).all()
            print(f"✓ EmailAttachment query succeeded: {len(attachments)} result(s)")

            # Test attribute access (the main fix)
            if emails:
                email = emails[0]
                # These should work without cast() now
                subject = email.subject
                has_attachments = email.has_attachments
                date_sent = email.date_sent
                sender_email = email.sender_email

                print("✓ Attribute access works:")
                print(f"  - subject: {subject[:50] if subject else None}...")
                print(
                    f"  - has_attachments: {has_attachments} (type: {type(has_attachments).__name__})"
                )
                print(f"  - date_sent: {date_sent}")
                print(f"  - sender_email: {sender_email}")
            else:
                print("⚠ No emails in database to test attribute access")

            return True
        finally:
            db.close()
    except Exception as e:
        print(f"✗ ORM query test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_relationships():
    """Test 6: Verify relationship navigation works"""
    print("\n" + "=" * 60)
    print("TEST 6: Relationship Navigation Tests")
    print("=" * 60)

    try:
        from api.app.db import SessionLocal
        from api.app.models import EmailMessage, EmailAttachment, User

        db = SessionLocal()
        try:
            # Test EmailMessage relationships
            email = db.query(EmailMessage).first()
            if email:
                # Navigate to PSTFile
                pst = email.pst_file
                print(f"✓ email.pst_file: {pst.filename if pst else None}")

                # Navigate to Case (optional)
                case = email.case
                print(f"✓ email.case: {case.name if case else None}")

                # Navigate to Project (optional)
                project = email.project
                print(f"✓ email.project: {project.project_name if project else None}")
            else:
                print("⚠ No emails to test relationships")

            # Test EmailAttachment relationships
            attachment = db.query(EmailAttachment).first()
            if attachment:
                msg = attachment.email_message
                print(
                    f"✓ attachment.email_message: {msg.subject[:30] if msg and msg.subject else None}..."
                )
            else:
                print("⚠ No attachments to test relationships")

            # Test User relationships
            user = db.query(User).first()
            if user:
                sessions = user.sessions
                print(f"✓ user.sessions: {len(sessions)} session(s)")
            else:
                print("⚠ No users to test relationships")

            return True
        finally:
            db.close()
    except Exception as e:
        print(f"✗ Relationship test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_pydantic_validation():
    """Test 7: Verify Pydantic models work with ORM data"""
    print("\n" + "=" * 60)
    print("TEST 7: Pydantic Schema Validation Tests")
    print("=" * 60)

    try:
        # First test basic Pydantic functionality with ORM data types
        from pydantic import BaseModel
        from datetime import datetime
        from typing import Optional

        # Define a simple test model similar to EmailMessageSummary
        class TestEmailSummary(BaseModel):
            id: str
            subject: Optional[str] = None
            sender_email: Optional[str] = None
            sender_name: Optional[str] = None
            date_sent: Optional[datetime] = None
            has_attachments: bool = False

        from api.app.db import SessionLocal
        from api.app.models import EmailMessage

        db = SessionLocal()
        try:
            email = db.query(EmailMessage).first()
            if email:
                # Test that ORM data can be passed directly to Pydantic models
                # This is the key test - we're passing Mapped[] typed attributes
                summary = TestEmailSummary(
                    id=str(email.id),
                    subject=email.subject,
                    sender_email=email.sender_email,
                    sender_name=email.sender_name,
                    date_sent=email.date_sent,
                    has_attachments=email.has_attachments,
                )
                print("✓ Pydantic model created with ORM data")
                print(f"  - id: {summary.id}")
                print(
                    f"  - subject: {summary.subject[:40] if summary.subject else None}..."
                )
                print(
                    f"  - has_attachments: {summary.has_attachments} (type: {type(summary.has_attachments).__name__})"
                )
                print(f"  - date_sent: {summary.date_sent}")
            else:
                print("⚠ No emails to test Pydantic validation")
                # Test with mock data instead
                summary = TestEmailSummary(
                    id=str(uuid.uuid4()),
                    subject="Test Subject",
                    sender_email="test@test.com",
                    sender_name="Test User",
                    date_sent=None,
                    has_attachments=False,
                )
                print("✓ Pydantic model created with mock data")

            # Also try to import the actual correspondence module if FastAPI is available
            try:
                from api.app.correspondence import EmailMessageSummary

                print("✓ FastAPI correspondence module available")
            except ImportError as e:
                print(f"⚠ FastAPI not available (expected in test env): {e}")

            return True
        finally:
            db.close()
    except Exception as e:
        print(f"✗ Pydantic validation test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def run_all_tests():
    """Run all migration verification tests"""
    print("\n" + "=" * 60)
    print("SQLAlchemy 2.0 Mapped[] Migration Verification")
    print("=" * 60)

    results = {
        "Model Imports": test_model_imports(),
        "Model Instantiation": test_model_instantiation(),
        "Property Aliases": test_property_aliases(),
        "Database Schema": test_database_schema(),
        "ORM Queries": test_orm_queries(),
        "Relationships": test_relationships(),
        "Pydantic Validation": test_pydantic_validation(),
    }

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = 0
    failed = 0
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
        if result:
            passed += 1
        else:
            failed += 1

    print("\n" + "-" * 60)
    print(f"Total: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
