"""Create runs, works, versions, identifiers, and content-addressed files.

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
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="running", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="completed_after_started",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'rolled_back')",
            name="status_values",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
    )
    op.create_table(
        "files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("file_format", sa.String(length=32), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("parse_quality", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "byte_size >= 0", name="byte_size_nonnegative"
        ),
        sa.CheckConstraint(
            "parse_quality IS NULL OR "
            "(parse_quality >= 0.0 AND parse_quality <= 1.0)",
            name="parse_quality_range",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="sha256_lowercase_hex"
        ),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name="fk_files_created_run_id_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_files"),
        sa.UniqueConstraint("sha256", name="uq_files_sha256"),
    )
    op.create_index(
        "ix_files_created_run_id", "files", ["created_run_id"], unique=False
    )
    op.create_table(
        "works",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("instrument_type", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("issuing_authority", sa.String(length=512), nullable=True),
        sa.Column("authority_tier", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("legal_force", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("resolution_status", sa.String(length=32), server_default="stub", nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "authority_tier IN "
            "('national', 'state', 'local', 'court', 'tribunal', 'regulator', "
            "'other', 'unknown')",
            name="authority_tier_values",
        ),
        sa.CheckConstraint(
            "instrument_type IN "
            "('act', 'rule', 'regulation', 'notification', 'order', 'circular', "
            "'policy', 'guideline', 'judgment', 'other', 'unknown')",
            name="instrument_type_values",
        ),
        sa.CheckConstraint(
            "legal_force IN ('binding', 'explanatory', 'mixed', 'unknown')",
            name="legal_force_values",
        ),
        sa.CheckConstraint(
            "resolution_status IN ('stub', 'resolved')",
            name="resolution_status_values",
        ),
        sa.CheckConstraint(
            "title IS NOT NULL OR resolution_status = 'stub'",
            name="title_required_when_resolved",
        ),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name="fk_works_created_run_id_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_works"),
    )
    op.create_index(
        "ix_works_authority_tier", "works", ["authority_tier"], unique=False
    )
    op.create_index(
        "ix_works_instrument_type", "works", ["instrument_type"], unique=False
    )
    op.create_index(
        "ix_works_resolution_status", "works", ["resolution_status"], unique=False
    )
    op.create_index(
        "ix_works_created_run_id", "works", ["created_run_id"], unique=False
    )
    op.create_table(
        "identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheme", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(scheme)) > 0", name="scheme_not_empty"
        ),
        sa.CheckConstraint(
            "length(trim(value)) > 0", name="value_not_empty"
        ),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name="fk_identifiers_created_run_id_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
            name="fk_identifiers_work_id_works",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_identifiers"),
        sa.UniqueConstraint("scheme", "value", name="uq_identifiers_scheme"),
    )
    op.create_index(
        "ix_identifiers_work_id", "identifiers", ["work_id"], unique=False
    )
    op.create_index(
        "ix_identifiers_created_run_id", "identifiers", ["created_run_id"], unique=False
    )
    op.create_table(
        "versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_label", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("is_consolidated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("consolidated_up_to", sa.Date(), nullable=True),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL "
            "OR effective_to >= effective_from",
            name="effective_date_range",
        ),
        sa.CheckConstraint(
            "version_label IS NOT NULL OR is_consolidated",
            name="label_required_unless_consolidated",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'withdrawn')",
            name="status_values",
        ),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name="fk_versions_created_run_id_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
            name="fk_versions_work_id_works",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_versions"),
        sa.UniqueConstraint(
            "work_id", "version_label", name="uq_versions_work_id"
        ),
    )
    op.create_index(
        "ix_versions_status_effective_from",
        "versions",
        ["status", "effective_from"],
        unique=False,
    )
    op.create_index(
        "ix_versions_status_effective_to",
        "versions",
        ["status", "effective_to"],
        unique=False,
    )
    op.create_index(
        "ix_versions_created_run_id", "versions", ["created_run_id"], unique=False
    )
    op.create_table(
        "version_files",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name="fk_version_files_created_run_id_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name="fk_version_files_file_id_files",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["versions.id"],
            name="fk_version_files_version_id_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("version_id", "file_id", name="pk_version_files"),
    )
    op.create_index(
        "ix_version_files_file_id", "version_files", ["file_id"], unique=False
    )
    op.create_index(
        "ix_version_files_created_run_id",
        "version_files",
        ["created_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_version_files_created_run_id", table_name="version_files")
    op.drop_index("ix_version_files_file_id", table_name="version_files")
    op.drop_table("version_files")
    op.drop_index("ix_versions_created_run_id", table_name="versions")
    op.drop_index("ix_versions_status_effective_to", table_name="versions")
    op.drop_index("ix_versions_status_effective_from", table_name="versions")
    op.drop_table("versions")
    op.drop_index("ix_identifiers_created_run_id", table_name="identifiers")
    op.drop_index("ix_identifiers_work_id", table_name="identifiers")
    op.drop_table("identifiers")
    op.drop_index("ix_works_created_run_id", table_name="works")
    op.drop_index("ix_works_resolution_status", table_name="works")
    op.drop_index("ix_works_instrument_type", table_name="works")
    op.drop_index("ix_works_authority_tier", table_name="works")
    op.drop_table("works")
    op.drop_index("ix_files_created_run_id", table_name="files")
    op.drop_table("files")
    op.drop_table("runs")
