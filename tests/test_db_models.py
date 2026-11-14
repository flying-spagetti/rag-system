from collections.abc import Iterator
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from regrag.db.models import (
    Base,
    Run,
    Version,
    VersionFile,
    Work,
    WorkFile,
    WorkIdentifier,
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
                source_url="https://example.test/one.pdf",
                file_format="pdf",
                byte_size=10,
            ),
            WorkFile(
                created_run_id=run.id,
                sha256=sha256,
                source_url="https://example.test/two.pdf",
                file_format="pdf",
                byte_size=10,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


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
        source_url="https://example.test/shared.pdf",
        file_format="pdf",
        byte_size=100,
    )
    db_session.add_all([version, file])
    db_session.flush()
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
