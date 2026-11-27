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

The table's natural key is the log slot — ``(user_id, date, meal, entry)`` — and
writes are upserts: the first write to a slot creates its row and a later write to
the same slot replaces it, so re-logging a meal replaces the prior row instead of
duplicating it. A different meal-time or a different entry is a different slot, and
therefore its own row.

Alongside it the diary keeps a per-user ``last_used`` roll — the last-used
tracking that answers "what did this user most recently log?" — written and read
through this module too, so the diary keeps a single data layer.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

__all__ = ("add_entry", "add_imported", "init_db", "get_top_used", "record_use")

#: The closed set of entry sources: a human-entered diary entry (``manual``) or
#: a value that arrived through an importer (``imported``). The point of the
#: CHECK constraint is that no third kind of source exists — not yet, and not by
#: accident of a typo'd write.
_VALID_SOURCES = frozenset({"manual", "imported"})

_CREATE_ENTRIES = (
    "CREATE TABLE IF NOT EXISTS entries ("
    "user_id TEXT NOT NULL, "
    "date TEXT NOT NULL, "
    "meal TEXT NOT NULL, "
    "entry TEXT NOT NULL, "
    "kcal REAL NOT NULL, "
    "note TEXT, "
    "source TEXT NOT NULL CHECK (source IN ('manual','imported')), "
    "created_at TEXT NOT NULL, "
    "PRIMARY KEY (user_id, date, meal, entry));"
)

_CREATE_LAST_USED = (
    "CREATE TABLE IF NOT EXISTS last_used ("
    "user_id TEXT NOT NULL, entry TEXT NOT NULL, meal TEXT NOT NULL, "
    "kcal REAL NOT NULL, last_used_at TEXT NOT NULL, use_count INTEGER NOT NULL, "
    "PRIMARY KEY (user_id, entry, meal));"
)


def init_db(path: str) -> sqlite3.Connection:
    """Create the diary's tables on ``path`` and return its connection.

    ``IF NOT EXISTS`` keeps each of them idempotent. The caller owns the
    returned connection from here on — the module never opens one behind your
    back.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_ENTRIES)
    conn.execute(_CREATE_LAST_USED)
    conn.commit()
    return conn


def add_entry(
    conn: sqlite3.Connection,
    user_id: str,
    date: str,
    meal: str,
    entry: str,
    kcal: float,
    note: str,
    source: str = "manual",
) -> None:
    """Write one diary entry through the single writer path.

    The write **upserts** on the log slot — ``(user_id, date, meal, entry)``: the
    first write to a slot creates its row and a later write to the same slot
    replaces it. Re-logging a meal therefore replaces the prior row instead of
    duplicating it, while a different meal-time or a different entry names a
    different slot and gets its own row.
    """
    if source not in _VALID_SOURCES:
        raise ValueError(
            f"source={source!r} is not one of: {', '.join(sorted(_VALID_SOURCES))}"
        )
    conn.execute(
        "INSERT INTO entries "
        "(user_id, date, meal, entry, kcal, note, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (user_id, date, meal, entry) DO UPDATE SET "
        "kcal = excluded.kcal, note = excluded.note, "
        "source = excluded.source, created_at = excluded.created_at",
        (
            user_id,
            date,
            meal,
            entry,
            kcal,
            note,
            source,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()


def add_imported(
    conn: sqlite3.Connection,
    user_id: str,
    date: str,
    meal: str,
    entry: str,
    kcal: float,
    note: str,
) -> None:
    """Write one entry stamped as ``imported`` — the importer's only door."""
    add_entry(conn, user_id, date, meal, entry, kcal, note, source="imported")


def get_entries(
    conn: sqlite3.Connection,
    user_id: str,
    date: str | None = None,
    meal: str | None = None,
) -> list[sqlite3.Row]:
    """Read one user's entries back, optionally filtered by date and/or meal."""
    sql = (
        "SELECT user_id, date, meal, entry, kcal, note, source, created_at "
        "FROM entries"
    )
    clauses: list[str] = ["user_id = ?"]
    params: list = [user_id]
    if date is not None:
        clauses.append("date = ?")
        params.append(date)
    if meal is not None:
        clauses.append("meal = ?")
        params.append(meal)
    sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY date, meal, entry"
    return conn.execute(sql, params).fetchall()


def record_use(
    conn: sqlite3.Connection,
    user_id: str,
    entry: str,
    meal: str,
    kcal: float,
    at: str | None = None,
) -> None:
    """Record that ``user_id`` used ``entry`` — the per-user last-used write.

    Each use bumps the entry's use count and stamps the moment of use, so the
    diary can later rank what a user relied on. ``at`` is injectable for tests
    and defaults to the wall clock.
    """
    moment = at if at is not None else datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO last_used (user_id, entry, meal, kcal, last_used_at, use_count) "
        "VALUES (?, ?, ?, ?, ?, 1) "
        "ON CONFLICT (user_id, entry, meal) DO UPDATE SET "
        "use_count = use_count + 1, last_used_at = excluded.last_used_at, "
        "meal = excluded.meal, kcal = excluded.kcal",
        (user_id, entry, meal, kcal, moment),
    )
    conn.commit()


def get_top_used(
    conn: sqlite3.Connection,
    user_id: str,
    limit: int = 5,
) -> list[sqlite3.Row]:
    """Return the entries ``user_id`` used most — best first, at most ``limit``.

    The ranking is most-recently-used first, with the use count and then the
    entry name breaking the remaining ties, so the top set comes back
    deterministic. ``limit`` defaults to 5 — the "Log again" window — and yields
    fewer rows when the user has used less than that.
    """
    return conn.execute(
        "SELECT user_id, entry, meal, kcal, last_used_at, use_count "
        "FROM last_used WHERE user_id = ? "
        "ORDER BY last_used_at DESC, use_count DESC, entry "
        "LIMIT ?",
        (user_id, limit),
    ).fetchall()
