"""The diary store: one SQLite file, one table, no stored totals.

A household food log is small enough to live in a single SQLite file: rows are
written rarely, read back newest-first, and the per-day calorie total is summed
on demand from the rows themselves, so it can never disagree with the data it
was computed from.

This module owns that store. It knows nothing about the reference dataset, and
the reference dataset knows nothing about diary rows -- they are different
questions with different answers, and this layer answers the diary one.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "DEFAULT_DB_PATH",
    "add_entry",
    "day_totals",
    "delete_entry",
    "get_entry",
    "init_db",
    "import_csv",
    "list_entries",
    "update_entry",
]

#: The diary CSV's header row, exactly — and deliberately no kind or source
#: column: the importer owns both, stamping every imported row
#: ``source="imported"`` and ``kind="food"``.
_IMPORT_COLUMNS = ("when", "title", "kcal")

#: The diary file: ``data/diary.db`` at the repo root, created on first use.
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "diary.db"

CREATE_ENTRIES = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    "when" TEXT NOT NULL,
    kind TEXT CHECK (kind IN ('meal', 'food')),
    title TEXT NOT NULL,
    note TEXT,
    kcal REAL,
    tags TEXT,
    source TEXT CHECK (source IN ('manual', 'imported')) NOT NULL DEFAULT 'manual'
)
"""

_ROW_COLUMNS = ("id", "when", "kind", "title", "note", "kcal", "tags", "source")
_UPDATABLE = ("when", "kind", "title", "note", "kcal", "tags", "source")

_INSERT_SQL = (
    'INSERT INTO entries ("when", kind, title, note, kcal, tags, source) '
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)
_LIST_SQL = (
    'SELECT id, "when", kind, title, note, kcal, tags, source '
    'FROM entries ORDER BY "when" DESC, id DESC'
)
_GET_SQL = (
    'SELECT id, "when", kind, title, note, kcal, tags, source '
    "FROM entries WHERE id = ?"
)
_UPDATE_SQL = (
    'UPDATE entries SET "when" = ?, kind = ?, title = ?, note = ?, kcal = ?, '
    "tags = ?, source = ? WHERE id = ?"
)
_DELETE_SQL = "DELETE FROM entries WHERE id = ?"
_TOTALS_SQL = (
    'SELECT date("when") AS day, SUM(kcal) AS total FROM entries '
    'GROUP BY date("when")'
)

_conn: sqlite3.Connection | None = None


def _connect(db: str | Path | sqlite3.Connection | None = None) -> sqlite3.Connection:
    """Return ``db`` when one is given, else the lazily-opened default store."""
    global _conn
    if db is None:
        if _conn is None:
            # "Created on first use" includes the directory it lands in.
            DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(DEFAULT_DB_PATH))
        return _conn
    if isinstance(db, sqlite3.Connection):
        return db
    path = Path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path))


def init_db(db: str | Path | sqlite3.Connection | None = None) -> sqlite3.Connection:
    """Open the diary store, creating the file and the table on first use."""
    conn = _connect(db)
    conn.execute(CREATE_ENTRIES)
    conn.commit()
    return conn


def add_entry(
    when: str,
    title: str,
    kind: str = "food",
    note: str | None = None,
    kcal: float | None = None,
    tags: str | None = None,
    source: str = "manual",
    *,
    db: str | Path | sqlite3.Connection | None = None,
) -> int:
    """Insert one diary entry and return its new row id."""
    conn = _connect(db)
    cursor = conn.execute(_INSERT_SQL, (when, kind, title, note, kcal, tags, source))
    conn.commit()
    return int(cursor.lastrowid)


def list_entries(
    *,
    db: str | Path | sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return the entries, newest first: ``ORDER BY "when" DESC, id DESC``."""
    rows = _connect(db).execute(_LIST_SQL).fetchall()
    return [_row(row) for row in rows]


def get_entry(
    entry_id: int,
    *,
    db: str | Path | sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Return one entry by id, or ``None`` when no such row exists."""
    row = _connect(db).execute(_GET_SQL, (entry_id,)).fetchone()
    return _row(row) if row is not None else None


def update_entry(
    entry_id: int,
    fields: Mapping[str, Any],
    *,
    db: str | Path | sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Apply the given field updates and return the entry as stored.

    ``fields`` is a partial mapping: only the keys it carries are written, so
    updating one column never requires echoing the rest.
    """
    conn = _connect(db)
    updates = {key: fields[key] for key in _UPDATABLE if key in fields}
    if updates:
        assignments = ", ".join(f'"{key}" = ?' for key in updates)
        conn.execute(
            f"UPDATE entries SET {assignments} WHERE id = ?",
            (*updates.values(), entry_id),
        )
        conn.commit()
    row = conn.execute(_GET_SQL, (entry_id,)).fetchone()
    return _row(row) if row is not None else None


def delete_entry(
    entry_id: int,
    *,
    db: str | Path | sqlite3.Connection | None = None,
) -> bool:
    """Delete the entry; ``True`` when a row was removed."""
    conn = _connect(db)
    cursor = conn.execute(_DELETE_SQL, (entry_id,))
    conn.commit()
    return cursor.rowcount > 0


def import_csv(
    path: str | Path,
    db: str | Path | sqlite3.Connection | None = None,
) -> int:
    """Import the diary CSV at ``path`` into the store, one row per eating occasion.

    The header row is required and must carry exactly the columns ``when,title,kcal`` —
    there is deliberately no kind or source column, so the importer owns both: every
    imported row is stamped ``source="imported"`` (the provenance of an imported row is the
    act of import, not anything the file claimed) and lands with ``kind="food"`` (the CSV
    has no meal slot of its own, and that is the diary's vocabulary for such a row).

    Each data row is written through :func:`add_entry` with ``source="imported"``. ``kcal``
    is parsed as a float; an empty or missing cell becomes ``NULL`` — an unmeasured eating
    occasion stays unmeasured rather than being guessed at.

    :param path: filesystem path to the diary CSV.
    :param db: the diary store to write into; the lazily-opened default store when omitted.
    :return: how many rows the import wrote.

    :raises ValueError: when the header row is missing or not exactly ``when,title,kcal``.
    """
    written = 0
    with open(path, "r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = [(name or "").strip() for name in (reader.fieldnames or [])]
        if sorted(header) != sorted(_IMPORT_COLUMNS):
            raise ValueError(
                f"diary CSV header must be exactly {list(_IMPORT_COLUMNS)}, got {header}"
            )
        for row in reader:
            when = (row.get("when") or "").strip()
            title = (row.get("title") or "").strip()
            kcal_raw = (row.get("kcal") or "").strip()
            if not when and not title and not kcal_raw:
                continue
            kcal = float(kcal_raw) if kcal_raw else None
            add_entry(
                when=when,
                title=title,
                kind="food",
                kcal=kcal,
                source="imported",
                db=db,
            )
            written += 1
    return written


def day_totals(
    *,
    db: str | Path | sqlite3.Connection | None = None,
) -> dict[str, float]:
    """Return per-day kcal totals keyed by ISO day.

    ``SUM(kcal)`` over ``date("when")``; a day whose entries all carry ``kcal =
    NULL`` sums to ``0.0`` and contributes nothing.
    """
    rows = _connect(db).execute(_TOTALS_SQL).fetchall()
    return {day: float(total) if total is not None else 0.0 for day, total in rows}


def _row(values: Any) -> dict[str, Any]:
    """Map a stored row onto the public field names."""
    return dict(zip(_ROW_COLUMNS, values))
