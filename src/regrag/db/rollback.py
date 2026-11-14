from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, exists, false, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from regrag.db.models import (
    Base,
    Run,
    Version,
    VersionFile,
    Work,
    WorkFile,
    WorkIdentifier,
)


def _has_references(model: type[Base]) -> ColumnElement[bool]:
    references = []
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            if foreign_key.column.table is model.__table__:
                child = table.alias()
                references.append(
                    exists(
                        select(1)
                        .select_from(child)
                        .where(child.c[foreign_key.parent.key] == foreign_key.column)
                    )
                )
    return or_(*references) if references else false()


def rollback_run(session: Session, run_id: UUID) -> None:
    run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    if run is None:
        raise ValueError(f"Run {run_id} does not exist")
    if run.status == "running":
        raise ValueError(f"Cannot roll back running run {run_id}")

    if run.status != "rolled_back":
        run.status = "rolled_back"
        run.completed_at = datetime.now(UTC)
    session.flush()

    rolled_back_runs = select(Run.id).where(Run.status == "rolled_back")
    session.execute(
        delete(VersionFile).where(
            VersionFile.created_run_id.in_(rolled_back_runs),
            ~_has_references(VersionFile),
        )
    )
    session.execute(
        delete(WorkIdentifier).where(
            WorkIdentifier.created_run_id.in_(rolled_back_runs),
            ~_has_references(WorkIdentifier),
        )
    )
    session.execute(
        delete(Version).where(
            Version.created_run_id.in_(rolled_back_runs),
            ~_has_references(Version),
        )
    )
    session.execute(
        delete(Work).where(
            Work.created_run_id.in_(rolled_back_runs),
            ~_has_references(Work),
        )
    )
    session.execute(
        delete(WorkFile).where(
            WorkFile.created_run_id.in_(rolled_back_runs),
            ~_has_references(WorkFile),
        )
    )
