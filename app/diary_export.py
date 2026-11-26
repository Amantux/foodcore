"""The diary export — the one-tap write of the device-local diary out.

The export is the write path by which diary content leaves the device, and the
only one: the caller chooses the destination (``dest_path``) and nothing about it
is defaulted or inferred.

The document it writes is versioned and closed — ``schemaVersion``, the diary's
entries under ``entries``, and the explicit ``tombstone`` marker when the diary
holds none. An export that follows a purge therefore writes the tombstoned,
zero-entry document: the file never carries stale content, and it states plainly
that there is nothing left to export rather than leaving a bare empty list behind.

The export reads the diary's entries table — the live store — and nothing else.
Undo snapshots, favourites and the last-used cache are derived stores, and are
not part of the export's view, so a stale snapshot cannot resurrect a record the
purge already cleared.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .purge import DIARY_PURGE_ENTRIES_TABLE

__all__ = [
    "DIARY_EXPORT_DOCUMENT_KEYS",
    "DIARY_EXPORT_EMPTY_STATE",
    "DIARY_EXPORT_ENTRY_KEYS",
    "DIARY_EXPORT_SCHEMA_VERSION",
    "DIARY_EXPORT_TOMBSTONE_KEY",
    "DiaryExportError",
    "export_diary",
]

#: The schema version of the exported diary document. Bumped only on an
#: incompatible change; a document from any other version is refused rather than
#: guessed at, mirroring the dataset loader's refusal of a future dataset file.
DIARY_EXPORT_SCHEMA_VERSION: int = 1

#: The top-level keys an exported diary document may carry.
DIARY_EXPORT_DOCUMENT_KEYS: frozenset[str] = frozenset(
    {"schemaVersion", "entries", "tombstone"}
)

#: The key of the explicit tombstone marker. An export whose diary holds no
#: entries carries it, and the marker's ``state`` names the diary's emptiness
#: rather than leaving a bare empty list to speak for itself.
DIARY_EXPORT_TOMBSTONE_KEY: str = "tombstone"

#: The state an exported diary that holds no entries is in.
DIARY_EXPORT_EMPTY_STATE: str = "empty"

#: The keys one exported diary entry may carry — exactly the plain-data shape the
#: diary's contract round-trips, and nothing more. Anything else is refused.
DIARY_EXPORT_ENTRY_KEYS: frozenset[str] = frozenset(
    {
        "entryId",
        "day",
        "food",
        "portion",
        "slot",
        "notes",
        "provenance",
        "createdAt",
        "updatedAt",
        "schemaVersion",
    }
)

#: The keys every exported diary document carries.
_REQUIRED_DOCUMENT_KEYS: frozenset[str] = frozenset({"schemaVersion", "entries"})


class DiaryExportError(Exception):
    """The diary export could not be written as an explicit document."""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _export_entry(row: sqlite3.Row) -> dict[str, Any]:
    """The exported plain-data form of one stored entry, refusing anything else."""
    exported = {
        "entryId": row["entry_id"],
        "day": row["day"],
        "food": row["food"],
        "portion": row["portion"],
        "slot": row["slot"],
        "notes": row["notes"],
        "provenance": row["provenance"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "schemaVersion": int(row["schema_version"]),
    }
    if set(exported) != DIARY_EXPORT_ENTRY_KEYS:
        raise DiaryExportError(
            f"the exported diary entry may only carry {sorted(DIARY_EXPORT_ENTRY_KEYS)}."
        )
    return exported


def _read_entries(db_path: str) -> list[dict[str, Any]]:
    """Read every diary entry from the live entries table, in export shape."""
    conn = _connect(db_path)
    try:
        if not _table_exists(conn, DIARY_PURGE_ENTRIES_TABLE):
            return []
        rows = conn.execute(
            "SELECT entry_id, day, food, portion, slot, notes, provenance, "
            "created_at, updated_at, schema_version FROM "
            f"{DIARY_PURGE_ENTRIES_TABLE} ORDER BY day, entry_id"
        ).fetchall()
    except sqlite3.Error as exc:
        raise DiaryExportError(
            f"the foodcore diary export from {db_path!r} could not read its entries: "
            f"{type(exc).__name__}."
        ) from None
    finally:
        conn.close()
    return [_export_entry(row) for row in rows]


def _entries_document(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The document an export carries when the diary it read holds entries."""
    return {"schemaVersion": DIARY_EXPORT_SCHEMA_VERSION, "entries": entries}


def _tombstone_document() -> dict[str, Any]:
    """The document an export carries when the diary it read holds none.

    The explicit tombstone marker is what makes a purged diary's export clearly
    empty rather than merely an empty list: the marker names the diary's state,
    and the entries list stays at zero.
    """
    return {
        "schemaVersion": DIARY_EXPORT_SCHEMA_VERSION,
        "entries": [],
        DIARY_EXPORT_TOMBSTONE_KEY: {"state": DIARY_EXPORT_EMPTY_STATE},
    }


def _validate_document(document: dict[str, Any]) -> None:
    keys = set(document)
    missing = _REQUIRED_DOCUMENT_KEYS - keys
    if missing:
        raise DiaryExportError(
            f"the exported diary document is missing required key(s): {', '.join(sorted(missing))}."
        )
    unknown = keys - DIARY_EXPORT_DOCUMENT_KEYS
    if unknown:
        raise DiaryExportError(
            f"the exported diary document may only carry {sorted(DIARY_EXPORT_DOCUMENT_KEYS)}: "
            f"{', '.join(sorted(unknown))}."
        )
    if DIARY_EXPORT_TOMBSTONE_KEY in keys and document["entries"]:
        raise DiaryExportError(
            "the exported diary document may not carry a tombstone alongside entries."
        )


def export_diary(
    entries_db_path: str,
    dest_path: str | Path,
) -> dict[str, Any]:
    """Write the diary store out as a versioned JSON file at ``dest_path``.

    Reads the very store the purge sweep clears — a read-only view, no duplicate
    store — and writes the user-chosen destination.

    A diary that holds entries exports as ``{"schemaVersion": .., "entries": [...]}``.
    A diary that holds none — which is what a purge leaves behind — exports as the
    tombstoned document, carrying the explicit ``tombstone`` marker and a zero-entry
    list: the next export after a purge is therefore clearly empty, and never stale.

    Returns the exported document.
    """
    entries = _read_entries(entries_db_path)
    document = _tombstone_document() if not entries else _entries_document(entries)
    _validate_document(document)
    Path(dest_path).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document
