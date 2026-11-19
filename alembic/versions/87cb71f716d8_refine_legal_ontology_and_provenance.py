"""refine legal ontology and provenance

Revision ID: 87cb71f716d8
Revises: 20261114_0001
Create Date: 2026-11-14 10:18:16.830778

"""
from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = '87cb71f716d8'
down_revision: str | None = '20261114_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalize_url(value: str) -> str:
    value = value.strip()
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return value
    if not parsed.scheme or not hostname:
        return value

    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"

    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    try:
        port = parsed.port
    except ValueError:
        return value

    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        host = f"{host}:{port}"

    return urlunsplit(
        (parsed.scheme.lower(), f"{userinfo}{host}", parsed.path or "/", parsed.query, "")
    )


def upgrade() -> None:
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
            name="source_url_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["created_run_id"],
            ["runs.id"],
            name="fk_file_sources_created_run_id_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name="fk_file_sources_file_id_files",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_file_sources"),
        sa.UniqueConstraint(
            "file_id",
            "normalized_url",
            name="uq_file_sources_file_id_normalized_url",
        ),
    )
    op.create_index(
        "ix_file_sources_created_run_id",
        "file_sources",
        ["created_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_file_sources_normalized_url",
        "file_sources",
        ["normalized_url"],
        unique=False,
    )
    connection = op.get_bind()
    for row in connection.execute(
        sa.text(
            "SELECT id, created_run_id, source_url, fetched_at "
            "FROM files ORDER BY id"
        )
    ).mappings():
        connection.execute(
            sa.text(
                "INSERT INTO file_sources "
                "(id, file_id, created_run_id, source_url, normalized_url, fetched_at) "
                "VALUES (:id, :file_id, :created_run_id, :source_url, "
                ":normalized_url, :fetched_at)"
            ),
            {
                "id": uuid4(),
                "file_id": row["id"],
                "created_run_id": row["created_run_id"],
                "source_url": row["source_url"],
                "normalized_url": _normalize_url(row["source_url"]),
                "fetched_at": row["fetched_at"],
            },
        )
    op.drop_column("files", "source_url")

    op.add_column(
        "identifiers",
        sa.Column("normalized_value", sa.String(length=1024), nullable=True),
    )
    for row in connection.execute(
        sa.text("SELECT id, scheme, value FROM identifiers ORDER BY id")
    ).mappings():
        scheme = row["scheme"].strip().lower()
        connection.execute(
            sa.text(
                "UPDATE identifiers SET scheme = :scheme, normalized_value = :value "
                "WHERE id = :id"
            ),
            {
                "id": row["id"],
                "scheme": scheme,
                "value": (
                    _normalize_url(row["value"])
                    if scheme == "url"
                    else row["value"].strip()
                ),
            },
        )
    op.alter_column("identifiers", "normalized_value", nullable=False)
    op.create_check_constraint(
        op.f("ck_identifiers_scheme_normalized"),
        "identifiers",
        "scheme = lower(trim(scheme))",
    )
    op.create_check_constraint(
        op.f("ck_identifiers_normalized_value_not_empty"),
        "identifiers",
        "length(trim(normalized_value)) > 0",
    )
    op.drop_constraint(op.f("uq_identifiers_scheme"), "identifiers", type_="unique")
    op.create_unique_constraint(
        op.f("uq_identifiers_scheme_normalized_value"),
        "identifiers",
        ["scheme", "normalized_value"],
    )

    op.add_column(
        "runs",
        sa.Column(
            "pipeline_name",
            sa.String(length=128),
            server_default="regrag",
            nullable=False,
        ),
    )
    op.add_column(
        "runs", sa.Column("pipeline_version", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "runs",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )

    op.drop_constraint(op.f("uq_versions_work_id"), "versions", type_="unique")
    op.create_unique_constraint(
        op.f("uq_versions_work_id_version_label"),
        "versions",
        ["work_id", "version_label"],
    )
    op.create_index(
        "uq_versions_work_consolidated_up_to",
        "versions",
        ["work_id", "consolidated_up_to"],
        unique=True,
        postgresql_where=sa.text("is_consolidated"),
    )
    op.create_check_constraint(
        op.f("ck_versions_consolidation_date_required"),
        "versions",
        "NOT is_consolidated OR consolidated_up_to IS NOT NULL",
    )

    op.add_column(
        "works",
        sa.Column(
            "jurisdiction_scope",
            sa.String(length=32),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.drop_constraint(
        op.f("ck_works_authority_tier_values"), "works", type_="check"
    )
    op.execute(
        """
        UPDATE works
        SET authority_tier = CASE authority_tier
            WHEN 'national' THEN 'central_legislation'
            WHEN 'state' THEN 'state_legislation'
            WHEN 'local' THEN 'subordinate_legislation'
            WHEN 'court' THEN 'high_court'
            WHEN 'tribunal' THEN 'other'
            ELSE authority_tier
        END
        """
    )
    op.create_check_constraint(
        op.f("ck_works_authority_tier_values"),
        "works",
        "authority_tier IN ('constitutional', 'supreme_court', 'high_court', "
        "'central_legislation', 'state_legislation', 'subordinate_legislation', "
        "'regulator', 'other', 'unknown')",
    )
    op.create_check_constraint(
        op.f("ck_works_jurisdiction_scope_values"),
        "works",
        "jurisdiction_scope IN "
        "('national', 'state', 'local', 'multi_state', 'territory', 'unknown')",
    )
    op.drop_constraint(
        op.f("ck_works_instrument_type_values"), "works", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_works_instrument_type_values"),
        "works",
        "instrument_type IN ('constitution', 'act', 'ordinance', 'rule', "
        "'regulation', 'notification', 'order', 'circular', 'direction', "
        "'scheme', 'policy', 'guideline', 'judgment', 'amendment', 'other', "
        "'unknown')",
    )
    op.drop_constraint(
        op.f("ck_works_resolution_status_values"), "works", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_works_resolution_status_values"),
        "works",
        "resolution_status IN ('stub', 'unresolved', 'ambiguous', 'resolved')",
    )
    op.drop_constraint(
        op.f("ck_works_title_required_when_resolved"), "works", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_works_title_required_when_resolved"),
        "works",
        "resolution_status != 'resolved' OR title IS NOT NULL",
    )
    op.create_index(
        "ix_works_jurisdiction_scope", "works", ["jurisdiction_scope"], unique=False
    )
    op.create_index(
        "ix_works_issuing_authority", "works", ["issuing_authority"], unique=False
    )
    op.create_index(
        "ix_works_legal_force", "works", ["legal_force"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_works_legal_force", table_name="works")
    op.drop_index("ix_works_issuing_authority", table_name="works")
    op.drop_index("ix_works_jurisdiction_scope", table_name="works")
    op.drop_constraint(
        op.f("ck_works_resolution_status_values"), "works", type_="check"
    )
    op.drop_constraint(
        op.f("ck_works_title_required_when_resolved"), "works", type_="check"
    )
    op.execute(
        "UPDATE works SET resolution_status = 'stub' "
        "WHERE resolution_status IN ('unresolved', 'ambiguous')"
    )
    op.create_check_constraint(
        op.f("ck_works_resolution_status_values"),
        "works",
        "resolution_status IN ('stub', 'resolved')",
    )
    op.create_check_constraint(
        op.f("ck_works_title_required_when_resolved"),
        "works",
        "title IS NOT NULL OR resolution_status = 'stub'",
    )
    op.drop_constraint(
        op.f("ck_works_instrument_type_values"), "works", type_="check"
    )
    op.execute(
        """
        UPDATE works
        SET instrument_type = CASE instrument_type
            WHEN 'constitution' THEN 'other'
            WHEN 'ordinance' THEN 'order'
            WHEN 'direction' THEN 'order'
            WHEN 'scheme' THEN 'policy'
            WHEN 'amendment' THEN 'act'
            ELSE instrument_type
        END
        """
    )
    op.create_check_constraint(
        op.f("ck_works_instrument_type_values"),
        "works",
        "instrument_type IN ('act', 'rule', 'regulation', 'notification', "
        "'order', 'circular', 'policy', 'guideline', 'judgment', 'other', "
        "'unknown')",
    )
    op.drop_constraint(
        op.f("ck_works_jurisdiction_scope_values"), "works", type_="check"
    )
    op.drop_constraint(
        op.f("ck_works_authority_tier_values"), "works", type_="check"
    )
    op.execute(
        """
        UPDATE works
        SET authority_tier = CASE authority_tier
            WHEN 'central_legislation' THEN 'national'
            WHEN 'state_legislation' THEN 'state'
            WHEN 'subordinate_legislation' THEN 'local'
            WHEN 'high_court' THEN 'court'
            WHEN 'supreme_court' THEN 'court'
            WHEN 'constitutional' THEN 'court'
            ELSE authority_tier
        END
        """
    )
    op.create_check_constraint(
        op.f("ck_works_authority_tier_values"),
        "works",
        "authority_tier IN ('national', 'state', 'local', 'court', "
        "'tribunal', 'regulator', 'other', 'unknown')",
    )
    op.drop_column("works", "jurisdiction_scope")

    op.drop_constraint(
        op.f("ck_versions_consolidation_date_required"),
        "versions",
        type_="check",
    )
    op.drop_index(
        "uq_versions_work_consolidated_up_to",
        table_name="versions",
        postgresql_where=sa.text("is_consolidated"),
    )
    op.drop_constraint(
        op.f("uq_versions_work_id_version_label"), "versions", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_versions_work_id"), "versions", ["work_id", "version_label"]
    )

    op.drop_column("runs", "metadata")
    op.drop_column("runs", "pipeline_version")
    op.drop_column("runs", "pipeline_name")

    op.drop_constraint(
        op.f("uq_identifiers_scheme_normalized_value"),
        "identifiers",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_identifiers_normalized_value_not_empty"),
        "identifiers",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_identifiers_scheme_normalized"), "identifiers", type_="check"
    )
    op.create_unique_constraint(
        op.f("uq_identifiers_scheme"), "identifiers", ["scheme", "value"]
    )
    op.drop_column("identifiers", "normalized_value")

    op.add_column("files", sa.Column("source_url", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE files AS f
        SET source_url = COALESCE(
            (SELECT min(fs.source_url) FROM file_sources AS fs WHERE fs.file_id = f.id),
            ''
        )
        """
    )
    op.alter_column("files", "source_url", nullable=False)
    op.drop_index("ix_file_sources_normalized_url", table_name="file_sources")
    op.drop_index("ix_file_sources_created_run_id", table_name="file_sources")
    op.drop_table("file_sources")
