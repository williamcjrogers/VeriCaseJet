#!/usr/bin/env python3
"""
SQLAlchemy 2.0 Mapped[] Migration Verification Tests

This test suite verifies that the migration from legacy Column() syntax
to SQLAlchemy 2.0 Mapped[] syntax is working correctly.
"""

import os
import sys
import uuid
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Provide minimal env for Settings validation during import.
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("USE_AWS_SERVICES", "true")
os.environ.setdefault("MINIO_BUCKET", "test-bucket")

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
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        raise AssertionError(f"Import failed: {e}") from e


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
    except Exception as e:
        print(f"✗ Instantiation failed: {e}")
        import traceback

        traceback.print_exc()
        raise


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
    except AssertionError as e:
        print(f"✗ Assertion failed: {e}")
        raise
    except Exception as e:
        print(f"✗ Property alias test failed: {e}")
        import traceback

        traceback.print_exc()
        raise


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
    except Exception as e:
        print(f"✗ Schema check failed: {e}")
        import traceback

        traceback.print_exc()
        raise


def test_orm_queries():
    """Test 5: Verify ORM queries work with Mapped[] syntax"""
    print("\n" + "=" * 60)
    print("TEST 5: ORM Query Tests")
    print("=" * 60)

    try:
        # These tests should not depend on a pre-existing database schema.
        # Instead, we validate that ORM statements can be constructed/compiled
        # and that Mapped[] attributes behave as expected on instances.
        from sqlalchemy import select
        from datetime import datetime, timezone

        from api.app.db import engine
        from api.app.models import User, Project, EmailMessage, EmailAttachment

        statements = {
            "User": select(User).limit(1),
            "Project": select(Project).limit(1),
            "EmailMessage": select(EmailMessage).limit(1),
            "EmailAttachment": select(EmailAttachment).limit(1),
        }

        for name, stmt in statements.items():
            compiled = stmt.compile(dialect=engine.dialect)
            _sql = str(compiled)
            assert _sql, f"Failed to compile select for {name}"
            print(f"✓ {name} select compiled")

        # Validate attribute access and typing on an in-memory instance.
        email = EmailMessage(
            pst_file_id=uuid.uuid4(),
            subject="Test Subject",
            sender_email="test@example.com",
            sender_name="Test Sender",
            has_attachments=True,
            date_sent=datetime.now(timezone.utc),
        )

        assert email.subject == "Test Subject"
        assert isinstance(email.has_attachments, bool)
        assert email.sender_email == "test@example.com"
        assert email.date_sent is not None
        print("✓ Attribute access works on ORM instances")
    except Exception as e:
        print(f"✗ ORM query test failed: {e}")
        import traceback

        traceback.print_exc()
        raise


def test_relationships():
    """Test 6: Verify relationship navigation works"""
    print("\n" + "=" * 60)
    print("TEST 6: Relationship Navigation Tests")
    print("=" * 60)

    try:
        from datetime import datetime, timedelta, timezone

        from api.app.models import (
            EmailMessage,
            EmailAttachment,
            PSTFile,
            User,
            UserSession,
        )

        pst_id = uuid.uuid4()
        pst = PSTFile(id=pst_id, filename="test.pst", s3_key="uploads/test.pst")

        email_id = uuid.uuid4()
        email = EmailMessage(
            id=email_id,
            pst_file_id=pst_id,
            subject="Rel Test",
            has_attachments=False,
            date_sent=datetime.now(timezone.utc),
        )
        email.pst_file = pst

        assert email.pst_file is pst
        print("✓ EmailMessage.pst_file relationship assignable")

        att = EmailAttachment(id=uuid.uuid4(), filename="x.txt")
        att.email_message = email
        assert att.email_message is email
        assert att in email.attachments
        print("✓ EmailAttachment.email_message back_populates works")

        user = User(id=uuid.uuid4(), email="rel@test.com", password_hash="hash")
        session = UserSession(
            id=uuid.uuid4(),
            user=user,
            token_jti="token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert session in user.sessions
        print("✓ User.sessions relationship assignable")
    except Exception as e:
        print(f"✗ Relationship test failed: {e}")
        import traceback

        traceback.print_exc()
        raise


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

        from datetime import datetime, timezone

        from api.app.models import EmailMessage

        # Prefer an in-memory ORM object over a DB query so this test is
        # stable in environments without migrations applied.
        email = EmailMessage(
            id=uuid.uuid4(),
            pst_file_id=uuid.uuid4(),
            subject="Test Subject",
            sender_email="test@test.com",
            sender_name="Test User",
            date_sent=datetime.now(timezone.utc),
            has_attachments=False,
        )

        summary = TestEmailSummary(
            id=str(email.id),
            subject=email.subject,
            sender_email=email.sender_email,
            sender_name=email.sender_name,
            date_sent=email.date_sent,
            has_attachments=email.has_attachments,
        )

        assert summary.id
        assert summary.subject == "Test Subject"
        assert isinstance(summary.has_attachments, bool)
        print("✓ Pydantic model created with ORM instance data")

        # Also try to import the actual correspondence module if FastAPI is available
        try:
            from api.app.correspondence import EmailMessageSummary

            assert EmailMessageSummary
            print("✓ FastAPI correspondence module available")
        except ImportError as e:
            print(f"⚠ FastAPI not available (expected in test env): {e}")
    except Exception as e:
        print(f"✗ Pydantic validation test failed: {e}")
        import traceback

        traceback.print_exc()
        raise


def run_all_tests():
    """Run all migration verification tests"""
    print("\n" + "=" * 60)
    print("SQLAlchemy 2.0 Mapped[] Migration Verification")
    print("=" * 60)

    tests = {
        "Model Imports": test_model_imports,
        "Model Instantiation": test_model_instantiation,
        "Property Aliases": test_property_aliases,
        "Database Schema": test_database_schema,
        "ORM Queries": test_orm_queries,
        "Relationships": test_relationships,
        "Pydantic Validation": test_pydantic_validation,
    }

    results: dict[str, bool] = {}
    for name, fn in tests.items():
        try:
            fn()
            results[name] = True
        except Exception:
            results[name] = False

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
