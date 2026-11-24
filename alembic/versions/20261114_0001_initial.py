"""Create the RegRAG identity schema.

Revision ID: 20261114_0001
Revises:
Create Date: 2026-11-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261114_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "pipeline_name", sa.String(128), server_default="regrag", nullable=False
        ),
        sa.Column("pipeline_version", sa.String(128)),
        sa.Column("status", sa.String(32), server_default="running", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'rolled_back')",
            name=op.f("ck_runs_status_values"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name=op.f("ck_runs_completed_after_started"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_table(
        "files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("file_format", sa.String(32), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("parse_quality", sa.Float()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_files_sha256_lowercase_hex"),
        ),
        sa.CheckConstraint(
            "byte_size >= 0", name=op.f("ck_files_byte_size_nonnegative")
        ),
        sa.CheckConstraint(
            "parse_quality IS NULL OR "
            "(parse_quality >= 0.0 AND parse_quality <= 1.0)",
            name=op.f("ck_files_parse_quality_range"),
        ),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name=op.f("fk_files_created_run_id_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint("sha256", name=op.f("uq_files_sha256")),
    )
    op.create_index("ix_files_created_run_id", "files", ["created_run_id"])

    op.create_table(
        "works",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512)),
        sa.Column("instrument_type", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("issuing_authority", sa.String(512)),
        sa.Column("authority_tier", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("jurisdiction_scope", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("legal_force", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("resolution_status", sa.String(32), server_default="stub", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "authority_tier IN ('constitutional', 'supreme_court', 'high_court', "
            "'central_legislation', 'state_legislation', 'subordinate_legislation', "
            "'regulator', 'other', 'unknown')",
            name=op.f("ck_works_authority_tier_values"),
        ),
        sa.CheckConstraint(
            "instrument_type IN ('constitution', 'act', 'ordinance', 'rule', "
            "'regulation', 'notification', 'order', 'circular', 'direction', "
            "'scheme', 'policy', 'guideline', 'judgment', 'amendment', 'other', "
            "'unknown')",
            name=op.f("ck_works_instrument_type_values"),
        ),
        sa.CheckConstraint(
            "jurisdiction_scope IN "
            "('national', 'state', 'local', 'multi_state', 'territory', 'unknown')",
            name=op.f("ck_works_jurisdiction_scope_values"),
        ),
        sa.CheckConstraint(
            "legal_force IN ('binding', 'explanatory', 'mixed', 'unknown')",
            name=op.f("ck_works_legal_force_values"),
        ),
        sa.CheckConstraint(
            "resolution_status != 'resolved' OR title IS NOT NULL",
            name=op.f("ck_works_title_required_when_resolved"),
        ),
        sa.CheckConstraint(
            "resolution_status IN ('stub', 'unresolved', 'ambiguous', 'resolved')",
            name=op.f("ck_works_resolution_status_values"),
        ),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name=op.f("fk_works_created_run_id_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_works")),
    )
    op.create_index("ix_works_created_run_id", "works", ["created_run_id"])

    op.create_table(
        "file_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(source_url)) > 0 AND length(trim(normalized_url)) > 0",
            name=op.f("ck_file_sources_source_url_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name=op.f("fk_file_sources_created_run_id_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_file_sources_file_id_files"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_sources")),
        sa.UniqueConstraint(
            "file_id",
            "normalized_url",
            name=op.f("uq_file_sources_file_id_normalized_url"),
        ),
    )
    op.create_index(
        "ix_file_sources_created_run_id", "file_sources", ["created_run_id"]
    )

    op.create_table(
        "identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheme", sa.String(64), nullable=False),
        sa.Column("value", sa.String(1024), nullable=False),
        sa.Column("normalized_value", sa.String(1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(normalized_value)) > 0",
            name=op.f("ck_identifiers_normalized_value_not_empty"),
        ),
        sa.CheckConstraint(
            "length(trim(scheme)) > 0", name=op.f("ck_identifiers_scheme_not_empty")
        ),
        sa.CheckConstraint(
            "length(trim(value)) > 0", name=op.f("ck_identifiers_value_not_empty")
        ),
        sa.CheckConstraint(
            "scheme = lower(trim(scheme))",
            name=op.f("ck_identifiers_scheme_normalized"),
        ),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name=op.f("fk_identifiers_created_run_id_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
            name=op.f("fk_identifiers_work_id_works"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identifiers")),
        sa.UniqueConstraint(
            "scheme",
            "normalized_value",
            name=op.f("uq_identifiers_scheme_normalized_value"),
        ),
    )
    op.create_index("ix_identifiers_created_run_id", "identifiers", ["created_run_id"])
    op.create_index("ix_identifiers_work_id", "identifiers", ["work_id"])

    op.create_table(
        "versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_label", sa.String(255)),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("is_consolidated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("issued_on", sa.Date()),
        sa.Column("published_on", sa.Date()),
        sa.Column("consolidated_up_to", sa.Date()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'withdrawn')",
            name=op.f("ck_versions_status_values"),
        ),
        sa.CheckConstraint(
            "NOT is_consolidated OR consolidated_up_to IS NOT NULL",
            name=op.f("ck_versions_consolidation_date_required"),
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL "
            "OR effective_to >= effective_from",
            name=op.f("ck_versions_effective_date_range"),
        ),
        sa.CheckConstraint(
            "version_label IS NOT NULL OR is_consolidated",
            name=op.f("ck_versions_label_required_unless_consolidated"),
        ),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name=op.f("fk_versions_created_run_id_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
            name=op.f("fk_versions_work_id_works"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_versions")),
        sa.UniqueConstraint(
            "work_id", "version_label", name=op.f("uq_versions_work_id_version_label")
        ),
    )
    op.create_index("ix_versions_created_run_id", "versions", ["created_run_id"])
    op.create_index(
        "uq_versions_work_consolidated_up_to",
        "versions",
        ["work_id", "consolidated_up_to"],
        unique=True,
        postgresql_where=sa.text("is_consolidated"),
    )

    op.create_table(
        "version_files",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name=op.f("fk_version_files_created_run_id_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_version_files_file_id_files"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["versions.id"],
            name=op.f("fk_version_files_version_id_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "version_id", "file_id", name=op.f("pk_version_files")
        ),
    )
    op.create_index(
        "ix_version_files_created_run_id", "version_files", ["created_run_id"]
    )
    op.create_index("ix_version_files_file_id", "version_files", ["file_id"])


def downgrade() -> None:
    op.drop_index("ix_version_files_file_id", table_name="version_files")
    op.drop_index("ix_version_files_created_run_id", table_name="version_files")
    op.drop_table("version_files")
    op.drop_index(
        "uq_versions_work_consolidated_up_to", table_name="versions"
    )
    op.drop_index("ix_versions_created_run_id", table_name="versions")
    op.drop_table("versions")
    op.drop_index("ix_identifiers_work_id", table_name="identifiers")
    op.drop_index("ix_identifiers_created_run_id", table_name="identifiers")
    op.drop_table("identifiers")
    op.drop_index("ix_file_sources_created_run_id", table_name="file_sources")
    op.drop_table("file_sources")
    op.drop_index("ix_works_created_run_id", table_name="works")
    op.drop_table("works")
    op.drop_index("ix_files_created_run_id", table_name="files")
    op.drop_table("files")
    op.drop_table("runs")
