"""Add ocr_corrections table for feedback loop.

Revision ID: 0003_ocr_corrections
Revises: 0002_add_stakeholder_roles
Create Date: 2025-12-12

This migration creates the ocr_corrections table to store manual text corrections
for documents and attachments, enabling a future adaptive OCR feedback loop.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision: str = "0003_ocr_corrections"
down_revision: str = "0002_add_stakeholder_roles"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    """Create ocr_corrections table."""
    op.create_table(
        "ocr_corrections",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("doc_id", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),  # document, email_attachment, etc.
        sa.Column("page", sa.Integer, nullable=True),
        sa.Column("bbox", JSONB, nullable=True),
        sa.Column("field_type", sa.String(50), nullable=True),  # date, amount, party, etc.
        sa.Column("original_text", sa.Text, nullable=False),
        sa.Column("corrected_text", sa.Text, nullable=False),
        sa.Column("ocr_engine", sa.String(50), nullable=True),
        sa.Column("ocr_confidence", sa.Float, nullable=True),
        sa.Column("scope", sa.String(50), server_default="project", nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("case_id", UUID(as_uuid=True), sa.ForeignKey("cases.id"), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Indexes for fast lookup and analysis
    op.create_index(
        "idx_ocr_corrections_doc",
        "ocr_corrections",
        ["doc_id", "source_type"]
    )
    op.create_index(
        "idx_ocr_corrections_lookup",
        "ocr_corrections",
        ["original_text", "field_type"]
    )
    op.create_index(
        "idx_ocr_corrections_project",
        "ocr_corrections",
        ["scope", "project_id"]
    )


def downgrade() -> None:
    """Drop ocr_corrections table."""
    op.drop_index("idx_ocr_corrections_project", table_name="ocr_corrections")
    op.drop_index("idx_ocr_corrections_lookup", table_name="ocr_corrections")
    op.drop_index("idx_ocr_corrections_doc", table_name="ocr_corrections")
    op.drop_table("ocr_corrections")
