"""add_contract_upload_models

Revision ID: 0018
Revises: 0017
Create Date: 2026-01-13 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    # ci_uploaded_contracts - stores uploaded contract documents and processing status
    op.create_table(
        "ci_uploaded_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contract_type_id", sa.Integer(), nullable=False),
        # File metadata
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("s3_key", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column(
            "content_type", sa.String(length=100), server_default="application/pdf"
        ),
        # Processing status
        sa.Column("status", sa.String(length=50), server_default="pending"),
        sa.Column("progress_percent", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Extracted content
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extracted_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("analysis_result", postgresql.JSONB(), nullable=True),
        # Counts
        sa.Column("total_clauses", sa.Integer(), server_default="0"),
        sa.Column("processed_clauses", sa.Integer(), server_default="0"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        # User tracking
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["contract_type_id"],
            ["ci_contract_types.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for uploaded_contracts
    op.create_index(
        "ix_ci_uploaded_contracts_project",
        "ci_uploaded_contracts",
        ["project_id"],
    )
    op.create_index(
        "ix_ci_uploaded_contracts_case",
        "ci_uploaded_contracts",
        ["case_id"],
    )
    op.create_index(
        "ix_ci_uploaded_contracts_status",
        "ci_uploaded_contracts",
        ["status"],
    )

    # ci_extracted_contract_clauses - stores individual clauses extracted from uploads
    op.create_table(
        "ci_extracted_contract_clauses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uploaded_contract_id", sa.Integer(), nullable=False),
        # Clause identification
        sa.Column("clause_number", sa.String(length=50), nullable=True),
        sa.Column("clause_title", sa.String(length=300), nullable=True),
        sa.Column("clause_text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        # Analysis metadata
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("entitlement_types", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        # Matching to standard clauses
        sa.Column("matched_standard_clause_id", sa.Integer(), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        # Vector reference
        sa.Column("vector_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["uploaded_contract_id"],
            ["ci_uploaded_contracts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["matched_standard_clause_id"],
            ["ci_contract_clauses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create index for extracted_clauses
    op.create_index(
        "ix_ci_extracted_clauses_contract",
        "ci_extracted_contract_clauses",
        ["uploaded_contract_id"],
    )


def downgrade():
    # Drop indexes first
    op.drop_index(
        "ix_ci_extracted_clauses_contract", table_name="ci_extracted_contract_clauses"
    )
    op.drop_index("ix_ci_uploaded_contracts_status", table_name="ci_uploaded_contracts")
    op.drop_index("ix_ci_uploaded_contracts_case", table_name="ci_uploaded_contracts")
    op.drop_index(
        "ix_ci_uploaded_contracts_project", table_name="ci_uploaded_contracts"
    )

    # Drop tables in reverse order (child first due to FK constraint)
    op.drop_table("ci_extracted_contract_clauses")
    op.drop_table("ci_uploaded_contracts")
