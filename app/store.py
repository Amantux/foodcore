"""The diary store — the single write surface for food entries.

foodcore is a library, not a service, and the deal is simple: the host owns the
data file. What foodcore owns is the one place an entry may be written, so that
every row in that table can later answer "where did this number come from" with a
source the schema itself will defend.

Two rules make that real:

1. **Closed provenance vocabulary.** ``source`` is ``manual`` or ``imported``
   and nothing else. The ``CHECK`` constraint is the hard boundary — a raw
   connection that tries to insert ``'recommender'`` or ``'planned'`` gets a
   ``sqlite3.IntegrityError`` — and :func:`add_entry` re-checks in Python before
   any SQL runs, so a caller hears a plain ``ValueError`` at the API edge instead
   of a constraint error surfacing from deep inside a write.

2. **One writer path.** :func:`add_entry` is the only function that writes;
   :func:`add_imported` is a thin wrapper that stamps ``source="imported"`` so an
   importer never negotiates provenance. The module exports no connection helper,
   no cursor and no ``exec`` passthrough: callers pass in the connection they got
   from :func:`init_db` and nothing else.

The table's natural key is ``(date, meal)`` — one row per day-meal — and writes
are plain ``INSERT``s: a re-import of the same day/meal either writes or fails,
it never silently overwrites.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

__all__ = ("add_entry", "add_imported", "init_db")

#: The closed set of entry sources: a human-entered diary entry (``manual``) or
#: a value that arrived through an importer (``imported``). The point of the
#: CHECK constraint is that no third kind of source exists — not yet, and not by
#: accident of a typo'd write.
_VALID_SOURCES = frozenset({"manual", "imported"})

_CREATE_ENTRIES = (
    "CREATE TABLE IF NOT EXISTS entries ("
    "date TEXT NOT NULL, meal TEXT NOT NULL, kcal REAL NOT NULL, note TEXT, "
    "source TEXT NOT NULL CHECK (source IN ('manual','imported')), "
    "created_at TEXT NOT NULL, "
    "PRIMARY KEY (date, meal));"
)


def init_db(path: str) -> sqlite3.Connection:
    """Create the ``entries`` table on ``path`` and return its connection.

    ``IF NOT EXISTS`` keeps it idempotent. The caller owns the returned
    connection from here on — the module never opens one behind your back.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_ENTRIES)
    conn.commit()
    return conn


def add_entry(
    conn: sqlite3.Connection,
    date: str,
    meal: str,
    kcal: float,
    note: str,
    source: str = "manual",
) -> None:
    """Write one diary entry through the single writer path."""
    if source not in _VALID_SOURCES:
        raise ValueError(
            f"source={source!r} is not one of: {', '.join(sorted(_VALID_SOURCES))}"
        )
    conn.execute(
        "INSERT INTO entries (date, meal, kcal, note, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (date, meal, kcal, note, source, datetime.utcnow().isoformat()),
    )
    conn.commit()


def add_imported(
    conn: sqlite3.Connection,
    date: str,
    meal: str,
    kcal: float,
    note: str,
) -> None:
    """Write one entry stamped as ``imported`` — the importer's only door."""
    add_entry(conn, date, meal, kcal, note, source="imported")


def get_entries(
    conn: sqlite3.Connection,
    date: str | None = None,
    meal: str | None = None,
) -> list[sqlite3.Row]:
    """Read entries back, optionally filtered by date and/or meal."""
    sql = "SELECT date, meal, kcal, note, source, created_at FROM entries"
    clauses: list[str] = []
    params: list = []
    if date is not None:
        clauses.append("date = ?")
        params.append(date)
    if meal is not None:
        clauses.append("meal = ?")
        params.append(meal)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY date, meal"
    return conn.execute(sql, params).fetchall()
