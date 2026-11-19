from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from regrag.db import rollback as rollback_module
from regrag.db.models import (
    Base,
    FileSource,
    Run,
    Version,
    VersionFile,
    Work,
    WorkFile,
    WorkIdentifier,
)
from regrag.db.normalization import (
    normalize_identifier_scheme,
    normalize_identifier_value,
)
from regrag.db.rollback import rollback_run
from regrag.settings import settings


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(settings.database_url)
    connection = engine.connect()
    transaction = connection.begin()
    schema = f"regrag_test_{uuid4().hex}"
    connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    connection.exec_driver_sql(f'SET search_path TO "{schema}"')
    connection = connection.execution_options(schema_translate_map={None: schema})
    Base.metadata.create_all(connection)
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def create_run(session: Session) -> Run:
    run = Run(status="succeeded")
    session.add(run)
    session.flush()
    return run


def create_work(session: Session, run: Run, title: str = "Example Act") -> Work:
    work = Work(
        created_run_id=run.id,
        title=title,
        instrument_type="act",
        resolution_status="resolved",
    )
    session.add(work)
    session.flush()
    return work


def test_duplicate_identifier_scheme_and_value_is_rejected(
    db_session: Session,
) -> None:
    run = create_run(db_session)
    first = create_work(db_session, run, "First Act")
    second = create_work(db_session, run, "Second Act")
    db_session.add_all(
        [
            WorkIdentifier(
                work_id=first.id,
                created_run_id=run.id,
                scheme="gazette_number",
                value="G.S.R. 123",
            ),
            WorkIdentifier(
                work_id=second.id,
                created_run_id=run.id,
                scheme="gazette_number",
                value="G.S.R. 123",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_effective_date_range_rejects_end_before_start(db_session: Session) -> None:
    run = create_run(db_session)
    work = create_work(db_session, run)
    db_session.add(
        Version(
            work_id=work.id,
            created_run_id=run.id,
            version_label="invalid-range",
            effective_from=date(2024, 1, 2),
            effective_to=date(2024, 1, 1),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_content_hash_is_rejected(db_session: Session) -> None:
    run = create_run(db_session)
    sha256 = "a" * 64
    db_session.add_all(
        [
            WorkFile(
                created_run_id=run.id,
                sha256=sha256,
                file_format="pdf",
                byte_size=10,
            ),
            WorkFile(
                created_run_id=run.id,
                sha256=sha256,
                file_format="pdf",
                byte_size=10,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_consolidated_version_is_unique_by_work_and_date(db_session: Session) -> None:
    run = create_run(db_session)
    work = create_work(db_session, run)
    db_session.add_all(
        [
            Version(
                work_id=work.id,
                created_run_id=run.id,
                is_consolidated=True,
                consolidated_up_to=date(2024, 1, 1),
            ),
            Version(
                work_id=work.id,
                created_run_id=run.id,
                is_consolidated=True,
                consolidated_up_to=date(2024, 1, 1),
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_version_label_is_unique_per_work(db_session: Session) -> None:
    run = create_run(db_session)
    work = create_work(db_session, run)
    db_session.add_all(
        [
            Version(
                work_id=work.id,
                created_run_id=run.id,
                version_label="2024",
            ),
            Version(
                work_id=work.id,
                created_run_id=run.id,
                version_label="2024",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_identifier_values_are_normalized_for_uniqueness(db_session: Session) -> None:
    run = create_run(db_session)
    first = create_work(db_session, run, "First Act")
    second = create_work(db_session, run, "Second Act")
    db_session.add_all(
        [
            WorkIdentifier(
                work_id=first.id,
                created_run_id=run.id,
                scheme=" URL ",
                value="HTTPS://Example.TEST:443/act#section",
            ),
            WorkIdentifier(
                work_id=second.id,
                created_run_id=run.id,
                scheme="url",
                value="https://example.test/act",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_identifier_normalized_values_match_the_normalizer(
    db_session: Session,
) -> None:
    run = create_run(db_session)
    work = create_work(db_session, run)
    db_session.add_all(
        [
            WorkIdentifier(
                work_id=work.id,
                created_run_id=run.id,
                scheme=" URL ",
                value="HTTPS://Example.TEST:443/act#section",
            ),
            WorkIdentifier(
                work_id=work.id,
                created_run_id=run.id,
                scheme="gazette_number",
                value=" G.S.R. 123 ",
            ),
        ]
    )
    db_session.flush()

    for identifier in db_session.scalars(select(WorkIdentifier)):
        assert identifier.scheme == normalize_identifier_scheme(identifier.scheme)
        assert identifier.normalized_value == normalize_identifier_value(
            identifier.scheme, identifier.value
        )


def test_file_can_have_multiple_source_urls(db_session: Session) -> None:
    run = create_run(db_session)
    file = WorkFile(
        created_run_id=run.id,
        sha256="d" * 64,
        file_format="pdf",
        byte_size=100,
    )
    db_session.add(file)
    db_session.flush()
    db_session.add_all(
        [
            FileSource(
                file_id=file.id,
                created_run_id=run.id,
                source_url="https://one.example.test/act.pdf",
            ),
            FileSource(
                file_id=file.id,
                created_run_id=run.id,
                source_url="https://two.example.test/act.pdf",
            ),
        ]
    )
    db_session.flush()
    assert len(file.sources) == 2


def test_duplicate_normalized_source_for_same_file_is_rejected(
    db_session: Session,
) -> None:
    run = create_run(db_session)
    file = WorkFile(
        created_run_id=run.id,
        sha256="e" * 64,
        file_format="pdf",
        byte_size=100,
    )
    db_session.add(file)
    db_session.flush()
    db_session.add_all(
        [
            FileSource(
                file_id=file.id,
                created_run_id=run.id,
                source_url="HTTPS://Example.TEST:443/a.pdf#page=1",
            ),
            FileSource(
                file_id=file.id,
                created_run_id=run.id,
                source_url="https://example.test/a.pdf",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("constraint", "run_values"),
    [
        ("ck_runs_status_values", {"status": "unknown"}),
        (
            "ck_runs_completed_after_started",
            {
                "started_at": datetime(2024, 1, 2, tzinfo=UTC),
                "completed_at": datetime(2024, 1, 1, tzinfo=UTC),
            },
        ),
    ],
)
def test_run_checks_are_enforced(
    db_session: Session, constraint: str, run_values: dict[str, object]
) -> None:
    run = Run(**run_values)
    db_session.add(run)
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert error.value.orig.diag.constraint_name == constraint


@pytest.mark.parametrize(
    ("constraint", "work_values"),
    [
        ("ck_works_instrument_type_values", {"instrument_type": "memo"}),
        ("ck_works_authority_tier_values", {"authority_tier": "national"}),
        ("ck_works_jurisdiction_scope_values", {"jurisdiction_scope": "federal"}),
        ("ck_works_legal_force_values", {"legal_force": "advisory"}),
        ("ck_works_resolution_status_values", {"resolution_status": "pending"}),
        (
            "ck_works_title_required_when_resolved",
            {"resolution_status": "resolved", "title": None},
        ),
    ],
)
def test_work_checks_are_enforced(
    db_session: Session, constraint: str, work_values: dict[str, object]
) -> None:
    run = create_run(db_session)
    work = Work(created_run_id=run.id, **work_values)
    db_session.add(work)
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert error.value.orig.diag.constraint_name == constraint


@pytest.mark.parametrize(
    ("constraint", "version_values"),
    [
        ("ck_versions_effective_date_range", {
            "effective_from": date(2024, 1, 2),
            "effective_to": date(2024, 1, 1),
        }),
        ("ck_versions_label_required_unless_consolidated", {
            "version_label": None,
            "is_consolidated": False,
        }),
        ("ck_versions_consolidation_date_required", {
            "version_label": None,
            "is_consolidated": True,
            "consolidated_up_to": None,
        }),
        ("ck_versions_status_values", {"status": "current"}),
    ],
)
def test_version_checks_are_enforced(
    db_session: Session, constraint: str, version_values: dict[str, object]
) -> None:
    run = create_run(db_session)
    work = create_work(db_session, run)
    values = {"version_label": "valid", **version_values}
    version = Version(
        work_id=work.id,
        created_run_id=run.id,
        **values,
    )
    db_session.add(version)
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert error.value.orig.diag.constraint_name == constraint


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("scheme", "", "ck_identifiers_scheme_not_empty"),
        ("value", "", "ck_identifiers_value_not_empty"),
    ],
)
def test_identifier_checks_are_enforced(
    db_session: Session, field: str, value: str, constraint: str
) -> None:
    run = create_run(db_session)
    work = create_work(db_session, run)
    identifier = WorkIdentifier(
        work_id=work.id,
        created_run_id=run.id,
        scheme="url",
        value="https://example.test/act",
    )
    setattr(identifier, field, value)
    if field == "value":
        identifier.normalized_value = "non-empty"
    db_session.add(identifier)
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert error.value.orig.diag.constraint_name == constraint


@pytest.mark.parametrize(
    ("scheme", "normalized_value", "constraint"),
    [
        (" URL ", "https://example.test/a", "ck_identifiers_scheme_normalized"),
        ("url", "", "ck_identifiers_normalized_value_not_empty"),
    ],
)
def test_identifier_normalization_checks_are_enforced(
    db_session: Session,
    scheme: str,
    normalized_value: str,
    constraint: str,
) -> None:
    run = create_run(db_session)
    work = create_work(db_session, run)
    with pytest.raises(IntegrityError) as error:
        db_session.execute(
            text(
                "INSERT INTO identifiers "
                "(id, work_id, created_run_id, scheme, value, normalized_value) "
                "VALUES (:id, :work_id, :run_id, :scheme, 'source', :normalized)"
            ),
            {
                "id": uuid4(),
                "work_id": work.id,
                "run_id": run.id,
                "scheme": scheme,
                "normalized": normalized_value,
            },
        )
    assert error.value.orig.diag.constraint_name == constraint


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("sha256", "not-a-hash", "ck_files_sha256_lowercase_hex"),
        ("byte_size", -1, "ck_files_byte_size_nonnegative"),
        ("parse_quality", 1.1, "ck_files_parse_quality_range"),
    ],
)
def test_file_checks_are_enforced(
    db_session: Session, field: str, value: object, constraint: str
) -> None:
    run = create_run(db_session)
    file = WorkFile(
        created_run_id=run.id,
        sha256="f" * 64,
        file_format="pdf",
        byte_size=100,
    )
    setattr(file, field, value)
    db_session.add(file)
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert error.value.orig.diag.constraint_name == constraint


def test_file_source_url_check_is_enforced(db_session: Session) -> None:
    run = create_run(db_session)
    file = WorkFile(
        created_run_id=run.id,
        sha256="1" * 64,
        file_format="pdf",
        byte_size=1,
    )
    db_session.add(file)
    db_session.flush()
    db_session.add(
        FileSource(file_id=file.id, created_run_id=run.id, source_url="")
    )
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert error.value.orig.diag.constraint_name == "ck_file_sources_source_url_not_empty"


def test_file_source_normalized_url_check_is_enforced(db_session: Session) -> None:
    run = create_run(db_session)
    file = WorkFile(
        created_run_id=run.id,
        sha256="3" * 64,
        file_format="pdf",
        byte_size=1,
    )
    db_session.add(file)
    db_session.flush()
    with pytest.raises(IntegrityError) as error:
        db_session.execute(
            text(
                "INSERT INTO file_sources "
                "(id, file_id, created_run_id, source_url, normalized_url) "
                "VALUES (:id, :file_id, :run_id, 'https://example.test', '')"
            ),
            {"id": uuid4(), "file_id": file.id, "run_id": run.id},
        )
    assert error.value.orig.diag.constraint_name == "ck_file_sources_source_url_not_empty"


def test_version_file_primary_key_rejects_duplicate_association(
    db_session: Session,
) -> None:
    run = create_run(db_session)
    work = create_work(db_session, run)
    version = Version(work_id=work.id, created_run_id=run.id, version_label="2024")
    file = WorkFile(
        created_run_id=run.id,
        sha256="2" * 64,
        file_format="pdf",
        byte_size=1,
    )
    db_session.add_all([version, file])
    db_session.flush()
    db_session.add_all(
        [
            VersionFile(
                version_id=version.id, file_id=file.id, created_run_id=run.id
            ),
            VersionFile(
                version_id=version.id, file_id=file.id, created_run_id=run.id
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_run_metadata_tracks_in_place_json_mutations(db_session: Session) -> None:
    run = create_run(db_session)
    run.run_metadata["source"] = "gazette"
    db_session.flush()
    db_session.expire(run)
    assert run.run_metadata == {"source": "gazette"}


def test_alembic_migration_matches_database_catalog() -> None:
    engine = create_engine(settings.database_url)
    schema_name = f"alembic_test_{uuid4().hex}"
    connection = engine.connect()
    try:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
        connection.commit()
        connection.exec_driver_sql(f'SET search_path TO "{schema_name}"')
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        connection.exec_driver_sql(f'SET search_path TO "{schema_name}"')

        inspector = inspect(connection)
        assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        for table in Base.metadata.sorted_tables:
            checks = {
                item["name"] for item in inspector.get_check_constraints(table.name)
            }
            expected_checks = {
                constraint.name
                for constraint in table.constraints
                if constraint.__class__.__name__ == "CheckConstraint"
            }
            assert checks == expected_checks, table.name
            uniques = {
                item["name"] for item in inspector.get_unique_constraints(table.name)
            }
            expected_uniques = {
                constraint.name
                for constraint in table.constraints
                if constraint.__class__.__name__ == "UniqueConstraint"
            }
            assert uniques == expected_uniques, table.name
            foreign_keys = {
                item["name"] for item in inspector.get_foreign_keys(table.name)
            }
            expected_foreign_keys = {
                foreign_key.constraint.name
                for column in table.columns
                for foreign_key in column.foreign_keys
            }
            assert foreign_keys == expected_foreign_keys, table.name
            index_names = {
                item["name"] for item in inspector.get_indexes(table.name)
            }
            assert {index.name for index in table.indexes} <= index_names, table.name
            assert inspector.get_pk_constraint(table.name)["name"] == next(
                constraint.name
                for constraint in table.constraints
                if constraint.__class__.__name__ == "PrimaryKeyConstraint"
            )

        version_indexes = {
            item["name"]: item for item in inspector.get_indexes("versions")
        }
        consolidated_index = version_indexes["uq_versions_work_consolidated_up_to"]
        assert consolidated_index["unique"]
        assert (
            consolidated_index["dialect_options"]["postgresql_where"]
            == "is_consolidated"
        )
        assert connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
        columns = {item["name"]: item for item in inspector.get_columns("versions")}
        assert columns["effective_from"]["type"].__class__.__name__ == "DATE"
    finally:
        connection.close()
        with engine.begin() as cleanup_connection:
            cleanup_connection.exec_driver_sql(
                f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'
            )
        engine.dispose()
def test_work_delete_is_restricted_when_metadata_references_it(
    db_session: Session,
) -> None:
    run = create_run(db_session)
    work = create_work(db_session, run)
    version = Version(
        work_id=work.id,
        created_run_id=run.id,
        version_label="2020",
    )
    identifier = WorkIdentifier(
        work_id=work.id,
        created_run_id=run.id,
        scheme="url",
        value="https://example.test/act",
    )
    db_session.add_all([version, identifier])
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Work).where(Work.id == work.id))


def test_run_delete_is_restricted_by_provenance(db_session: Session) -> None:
    run = create_run(db_session)
    create_work(db_session, run)

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Run).where(Run.id == run.id))


def test_rollback_preserves_shared_file_until_linking_run_is_rolled_back(
    db_session: Session,
) -> None:
    file_run = create_run(db_session)
    linking_run = create_run(db_session)
    work = create_work(db_session, linking_run)
    version = Version(
        work_id=work.id,
        created_run_id=linking_run.id,
        version_label="2024",
    )
    file = WorkFile(
        created_run_id=file_run.id,
        sha256="c" * 64,
        file_format="pdf",
        byte_size=100,
    )
    db_session.add_all([version, file])
    db_session.flush()
    db_session.add(
        FileSource(
            file_id=file.id,
            created_run_id=file_run.id,
            source_url="https://example.test/shared.pdf",
        )
    )
    link = VersionFile(
        version_id=version.id,
        file_id=file.id,
        created_run_id=linking_run.id,
    )
    db_session.add(link)
    db_session.flush()
    file_id = file.id
    link_id = (link.version_id, link.file_id)

    rollback_run(db_session, file_run.id)
    db_session.flush()

    assert db_session.get(WorkFile, file_id) is not None
    assert db_session.get(VersionFile, link_id) is not None
    rolled_back_run = db_session.get(Run, file_run.id)
    assert rolled_back_run is not None
    assert rolled_back_run.status == "rolled_back"

    rollback_run(db_session, file_run.id)
    db_session.flush()
    assert db_session.get(WorkFile, file_id) is not None

    rollback_run(db_session, linking_run.id)
    db_session.flush()

    assert db_session.get(VersionFile, link_id) is None
    assert db_session.get(WorkFile, file_id) is None


def test_rollback_preserves_work_referenced_by_later_run(
    db_session: Session,
) -> None:
    work_run = create_run(db_session)
    version_run = create_run(db_session)
    work = Work(created_run_id=work_run.id, resolution_status="stub")
    db_session.add(work)
    db_session.flush()
    version = Version(
        work_id=work.id,
        created_run_id=version_run.id,
        version_label="2024",
    )
    db_session.add(version)
    db_session.flush()
    work_id = work.id
    version_id = version.id

    rollback_run(db_session, work_run.id)
    db_session.flush()

    assert db_session.get(Work, work_id) is not None
    assert db_session.get(Version, version_id) is not None

    rollback_run(db_session, version_run.id)
    db_session.flush()

    assert db_session.get(Version, version_id) is None
    assert db_session.get(Work, work_id) is None


def test_rollback_sweep_covers_every_run_provenance_table() -> None:
    provenance_tables = {
        table
        for table in Base.metadata.tables.values()
        if "created_run_id" in table.c
    }
    assert set(rollback_module._rollback_tables()) == provenance_tables


def test_rollback_reports_deleted_and_preserved_rows(db_session: Session) -> None:
    work_run = create_run(db_session)
    later_run = create_run(db_session)
    work = Work(created_run_id=work_run.id, resolution_status="stub")
    db_session.add(work)
    db_session.flush()
    version = Version(
        work_id=work.id,
        created_run_id=later_run.id,
        version_label="2024",
    )
    db_session.add(version)
    db_session.flush()

    report = rollback_run(db_session, work_run.id)

    assert report["works"] == {"deleted": 0, "preserved_referenced": 1}


def test_rollback_refuses_unknown_run(db_session: Session) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        rollback_run(db_session, uuid4())


def test_rollback_refuses_running_run(db_session: Session) -> None:
    run = Run(status="running")
    db_session.add(run)
    db_session.flush()

    with pytest.raises(ValueError, match="Cannot roll back running run"):
        rollback_run(db_session, run.id)

    db_session.expire(run)
    assert run.status == "running"


def test_rollback_accepts_failed_run(db_session: Session) -> None:
    run = Run(status="failed")
    db_session.add(run)
    db_session.flush()

    rollback_run(db_session, run.id)

    db_session.expire(run)
    assert run.status == "rolled_back"


def test_rollback_sweep_is_atomic_on_failure(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = create_run(db_session)
    create_work(db_session, run)

    def fail(_table: object) -> object:
        raise RuntimeError("forced sweep failure")

    monkeypatch.setattr(rollback_module, "_has_references", fail)
    with pytest.raises(RuntimeError, match="forced sweep failure"):
        rollback_run(db_session, run.id)

    monkeypatch.undo()
    db_session.expire_all()
    assert db_session.get(Run, run.id).status == "succeeded"
    assert db_session.query(Work).filter_by(created_run_id=run.id).count() == 1


def test_two_connections_can_rollback_the_same_run_safely() -> None:
    engine = create_engine(settings.database_url)
    schema = f"rollback_race_{uuid4().hex}"
    run_id = uuid4()
    barrier = Barrier(2)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            Base.metadata.create_all(
                connection.execution_options(schema_translate_map={None: schema})
            )

        with engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            session = Session(bind=connection)
            run = Run(status="succeeded")
            session.add(run)
            session.flush()
            session.add(Work(created_run_id=run.id, resolution_status="stub"))
            session.commit()
            run_id = run.id
            session.close()

        def roll_back() -> dict[str, dict[str, int]]:
            with engine.connect() as connection:
                connection.exec_driver_sql(f'SET search_path TO "{schema}"')
                connection.commit()
                session = Session(bind=connection)
                try:
                    barrier.wait()
                    with session.begin():
                        return rollback_run(session, run_id)
                finally:
                    session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(roll_back), executor.submit(roll_back)]
            results = [future.result() for future in futures]

        assert sum(result.get("works", {}).get("deleted", 0) for result in results) == 1
        with engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            session = Session(bind=connection)
            assert session.get(Run, run_id).status == "rolled_back"
            assert session.query(Work).filter_by(created_run_id=run_id).count() == 0
            session.close()
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()
