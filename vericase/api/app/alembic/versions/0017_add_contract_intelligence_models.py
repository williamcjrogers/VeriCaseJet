"""add_contract_intelligence_models

Revision ID: 0017
Revises: 0016_add_corpus_learning_results
Create Date: 2026-01-13 01:35:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0017"
down_revision = "0016_add_corpus_learning_results"
branch_labels = None
depends_on = None


def upgrade():
    # ci_contract_types
    op.create_table(
        "ci_contract_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # ci_contract_clauses
    op.create_table(
        "ci_contract_clauses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contract_type_id", sa.Integer(), nullable=False),
        sa.Column("clause_number", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("semantic_patterns", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("related_clauses", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("entitlement_types", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column(
            "mitigation_strategies", postgresql.ARRAY(sa.String()), nullable=True
        ),
        sa.Column("time_implications", sa.Text(), nullable=True),
        sa.Column("cost_implications", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["contract_type_id"],
            ["ci_contract_types.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ci_case_law_references
    op.create_table(
        "ci_case_law_references",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contract_type_id", sa.Integer(), nullable=False),
        sa.Column("clause_id", sa.Integer(), nullable=True),
        sa.Column("case_name", sa.String(length=200), nullable=False),
        sa.Column("citation", sa.String(length=100), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("key_principles", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("implications", sa.Text(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["clause_id"],
            ["ci_contract_clauses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["contract_type_id"],
            ["ci_contract_types.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ci_project_contracts
    op.create_table(
        "ci_project_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_type_id", sa.Integer(), nullable=False),
        sa.Column("contract_reference", sa.String(length=100), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("completion_date", sa.DateTime(), nullable=True),
        sa.Column("contract_value", sa.Float(), nullable=True),
        sa.Column("special_provisions", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["contract_type_id"],
            ["ci_contract_types.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ci_correspondence_analyses
    op.create_table(
        "ci_correspondence_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_contract_id", sa.Integer(), nullable=False),
        sa.Column("correspondence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("analysis_result", sa.JSON(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("entitlement_score", sa.Float(), nullable=True),
        sa.Column("primary_clauses", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_contract_id"],
            ["ci_project_contracts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ci_correspondence_clause_matches
    op.create_table(
        "ci_correspondence_clause_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("clause_id", sa.Integer(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("keyword_matches", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("pattern_matches", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("context_snippet", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("entitlement_types", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["ci_correspondence_analyses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["clause_id"],
            ["ci_contract_clauses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ci_contract_knowledge_vectors
    op.create_table(
        "ci_contract_knowledge_vectors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.String(length=50), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding_vector", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ci_contract_knowledge_vectors_entity",
        "ci_contract_knowledge_vectors",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_ci_contract_knowledge_vectors_model",
        "ci_contract_knowledge_vectors",
        ["embedding_model"],
        unique=False,
    )

    # ci_ai_training_examples
    op.create_table(
        "ci_ai_training_examples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contract_type_id", sa.Integer(), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["contract_type_id"],
            ["ci_contract_types.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ci_plugin_configurations
    op.create_table(
        "ci_plugin_configurations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plugin_name", sa.String(length=100), nullable=False),
        sa.Column("contract_type", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plugin_name"),
    )


def downgrade():
    op.drop_table("ci_plugin_configurations")
    op.drop_table("ci_ai_training_examples")
    op.drop_index(
        "ix_ci_contract_knowledge_vectors_model",
        table_name="ci_contract_knowledge_vectors",
    )
    op.drop_index(
        "ix_ci_contract_knowledge_vectors_entity",
        table_name="ci_contract_knowledge_vectors",
    )
    op.drop_table("ci_contract_knowledge_vectors")
    op.drop_table("ci_correspondence_clause_matches")
    op.drop_table("ci_correspondence_analyses")
    op.drop_table("ci_project_contracts")
    op.drop_table("ci_case_law_references")
    op.drop_table("ci_contract_clauses")
    op.drop_table("ci_contract_types")
