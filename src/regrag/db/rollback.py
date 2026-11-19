from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, exists, false, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.schema import Table

from regrag.db.models import Base, Run


def _rollback_tables() -> list[Table]:
    return [
        table
        for table in reversed(Base.metadata.sorted_tables)
        if "created_run_id" in table.c
    ]


def _has_references(table: Table) -> ColumnElement[bool]:
    references = []
    for child_table in Base.metadata.tables.values():
        for foreign_key in child_table.foreign_keys:
            if foreign_key.column.table is table:
                child = child_table.alias()
                references.append(
                    exists(
                        select(1)
                        .select_from(child)
                        .where(child.c[foreign_key.parent.key] == foreign_key.column)
                    )
                )
    return or_(*references) if references else false()


def rollback_run(session: Session, run_id: UUID) -> dict[str, dict[str, int]]:
    report: dict[str, dict[str, int]] = {}

    with session.begin_nested():
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
        for table in _rollback_tables():
            owned_rows = table.c.created_run_id.in_(rolled_back_runs)
            preserved = session.scalar(
                select(func.count())
                .select_from(table)
                .where(owned_rows, _has_references(table))
            )
            result = session.execute(
                delete(table)
                .where(owned_rows, ~_has_references(table))
            )
            deleted = result.rowcount or 0
            if deleted or preserved:
                report[table.name] = {
                    "deleted": deleted,
                    "preserved_referenced": preserved or 0,
                }

    session.expire_all()
    return report
