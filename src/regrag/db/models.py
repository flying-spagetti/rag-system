from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    validates,
)

from regrag.db.normalization import (
    normalize_identifier_scheme,
    normalize_identifier_value,
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'rolled_back')",
            name="status_values",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="completed_after_started",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    pipeline_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default="regrag", server_default="regrag"
    )
    pipeline_version: Mapped[str | None] = mapped_column(String(128))
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", MutableDict.as_mutable(JSONB), default=dict, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="running", server_default="running"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class Work(Base):
    __tablename__ = "works"
    __table_args__ = (
        CheckConstraint(
            "instrument_type IN "
            "('constitution', 'act', 'ordinance', 'rule', 'regulation', "
            "'notification', 'order', 'circular', 'direction', 'scheme', "
            "'policy', 'guideline', 'judgment', 'amendment', 'other', 'unknown')",
            name="instrument_type_values",
        ),
        CheckConstraint(
            "authority_tier IN "
            "('constitutional', 'supreme_court', 'high_court', "
            "'central_legislation', 'state_legislation', 'subordinate_legislation', "
            "'regulator', 'other', 'unknown')",
            name="authority_tier_values",
        ),
        CheckConstraint(
            "jurisdiction_scope IN "
            "('national', 'state', 'local', 'multi_state', 'territory', 'unknown')",
            name="jurisdiction_scope_values",
        ),
        CheckConstraint(
            "legal_force IN ('binding', 'explanatory', 'mixed', 'unknown')",
            name="legal_force_values",
        ),
        CheckConstraint(
            "resolution_status IN ('stub', 'unresolved', 'ambiguous', 'resolved')",
            name="resolution_status_values",
        ),
        CheckConstraint(
            "resolution_status != 'resolved' OR title IS NOT NULL",
            name="title_required_when_resolved",
        ),
        Index("ix_works_resolution_status", "resolution_status"),
        Index("ix_works_instrument_type", "instrument_type"),
        Index("ix_works_authority_tier", "authority_tier"),
        Index("ix_works_jurisdiction_scope", "jurisdiction_scope"),
        Index("ix_works_issuing_authority", "issuing_authority"),
        Index("ix_works_legal_force", "legal_force"),
        Index("ix_works_created_run_id", "created_run_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    created_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(512))
    instrument_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    issuing_authority: Mapped[str | None] = mapped_column(String(512))
    authority_tier: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    jurisdiction_scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    legal_force: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    resolution_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="stub", server_default="stub"
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    versions: Mapped[list["Version"]] = relationship(
        back_populates="work", passive_deletes="all"
    )
    identifiers: Mapped[list["WorkIdentifier"]] = relationship(
        back_populates="work", passive_deletes="all"
    )


class Version(Base):
    __tablename__ = "versions"
    __table_args__ = (
        UniqueConstraint("work_id", "version_label"),
        Index(
            "uq_versions_work_consolidated_up_to",
            "work_id",
            "consolidated_up_to",
            unique=True,
            postgresql_where=text("is_consolidated"),
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL "
            "OR effective_to >= effective_from",
            name="effective_date_range",
        ),
        CheckConstraint(
            "version_label IS NOT NULL OR is_consolidated",
            name="label_required_unless_consolidated",
        ),
        CheckConstraint(
            "NOT is_consolidated OR consolidated_up_to IS NOT NULL",
            name="consolidation_date_required",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded', 'withdrawn')",
            name="status_values",
        ),
        Index("ix_versions_status_effective_from", "status", "effective_from"),
        Index("ix_versions_status_effective_to", "status", "effective_to"),
        Index("ix_versions_created_run_id", "created_run_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    work_id: Mapped[UUID] = mapped_column(
        ForeignKey("works.id", ondelete="RESTRICT"), nullable=False
    )
    created_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    version_label: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    is_consolidated: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    issued_on: Mapped[date | None] = mapped_column(Date)
    published_on: Mapped[date | None] = mapped_column(Date)
    consolidated_up_to: Mapped[date | None] = mapped_column(Date)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    work: Mapped[Work] = relationship(back_populates="versions")
    file_links: Mapped[list["VersionFile"]] = relationship(
        back_populates="version", passive_deletes="all"
    )


class WorkIdentifier(Base):
    __tablename__ = "identifiers"
    __table_args__ = (
        UniqueConstraint("scheme", "normalized_value"),
        CheckConstraint(
            "scheme = lower(trim(scheme))", name="scheme_normalized"
        ),
        CheckConstraint("length(trim(scheme)) > 0", name="scheme_not_empty"),
        CheckConstraint("length(trim(value)) > 0", name="value_not_empty"),
        CheckConstraint(
            "length(trim(normalized_value)) > 0",
            name="normalized_value_not_empty",
        ),
        Index("ix_identifiers_work_id", "work_id"),
        Index("ix_identifiers_created_run_id", "created_run_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    work_id: Mapped[UUID] = mapped_column(
        ForeignKey("works.id", ondelete="RESTRICT"), nullable=False
    )
    created_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    scheme: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    work: Mapped[Work] = relationship(back_populates="identifiers")

    @validates("scheme")
    def normalize_scheme(self, _key: str, value: str) -> str:
        scheme = normalize_identifier_scheme(value)
        if self.value:
            self.normalized_value = normalize_identifier_value(scheme, self.value)
        return scheme

    @validates("value")
    def normalize_value(self, _key: str, value: str) -> str:
        self.normalized_value = normalize_identifier_value(self.scheme, value)
        return value


class WorkFile(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("sha256"),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="sha256_lowercase_hex"
        ),
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint(
            "parse_quality IS NULL OR "
            "(parse_quality >= 0.0 AND parse_quality <= 1.0)",
            name="parse_quality_range",
        ),
        Index("ix_files_created_run_id", "created_run_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    created_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_format: Mapped[str] = mapped_column(String(32), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    parse_quality: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version_links: Mapped[list["VersionFile"]] = relationship(
        back_populates="file", passive_deletes="all"
    )
    sources: Mapped[list["FileSource"]] = relationship(
        back_populates="file", passive_deletes="all"
    )

    @property
    def storage_key(self) -> str:
        return f"sha256/{self.sha256[:2]}/{self.sha256}"


class FileSource(Base):
    __tablename__ = "file_sources"
    __table_args__ = (
        UniqueConstraint("file_id", "normalized_url"),
        CheckConstraint(
            "length(trim(source_url)) > 0 AND length(trim(normalized_url)) > 0",
            name="source_url_not_empty",
        ),
        Index("ix_file_sources_created_run_id", "created_run_id"),
        Index("ix_file_sources_normalized_url", "normalized_url"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("files.id", ondelete="RESTRICT"), nullable=False
    )
    created_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    file: Mapped[WorkFile] = relationship(back_populates="sources")

    @validates("source_url")
    def normalize_source_url(self, _key: str, value: str) -> str:
        self.normalized_url = normalize_identifier_value("url", value)
        return value


class VersionFile(Base):
    __tablename__ = "version_files"
    __table_args__ = (
        Index("ix_version_files_file_id", "file_id"),
        Index("ix_version_files_created_run_id", "created_run_id"),
    )

    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("versions.id", ondelete="RESTRICT"), primary_key=True
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("files.id", ondelete="RESTRICT"), primary_key=True
    )
    created_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[Version] = relationship(back_populates="file_links")
    file: Mapped[WorkFile] = relationship(back_populates="version_links")
