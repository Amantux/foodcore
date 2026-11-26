"""The diary: minimal SQLite-backed diary with a provenance CHECK.

A diary entry is either something a human actually wrote down (``manual``) or
something that arrived through an import (``imported``). The two are different
facts, and the storage layer has to refuse to let one silently become the
other.

The trust boundary sits at this module, not at the payload: the diary assigns
``provenance`` itself and reads the payload's claim only to refuse it, so an
import cannot claim ``manual`` or mint a provenance of its own. The ``CHECK``
constraint on the ``provenance`` column is the backstop that keeps even a raw,
seam-less write inside the allowed vocabulary.

Why SQLite, and why a CHECK:

* the diary is small rows a host app keeps in its own data dir -- the same
  reasoning as the reference dataset: a file, not a server, not in-memory JSON;
* ``sqlite3`` is the standard library, so the zero-dependency rule holds;
* a CHECK makes the vocabulary a property of the storage, so a write that never
  went through the seam is still refused rather than silently stored.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

from .provenance import VocabularyError

#: The provenance vocabulary of the diary. ``manual`` is set only by an
#: explicit human/operator path; ``imported`` is what an import assigns.
PROVENANCE_MANUAL = "manual"
PROVENANCE_IMPORTED = "imported"
ALLOWED_PROVENANCES: frozenset[str] = frozenset({PROVENANCE_MANUAL, PROVENANCE_IMPORTED})

#: The provenance an import assigns -- and the only one an import may claim.
#: Assigned here, never copied from the payload: an import is, by definition, not
#: a human entry, so a payload claiming anything else (``manual`` included) is a
#: manual entry trying to ride an import and is refused at the seam.
IMPORTED_PROVENANCE = PROVENANCE_IMPORTED
IMPORT_ALLOWED_PROVENANCES: frozenset[str] = frozenset({PROVENANCE_IMPORTED})

#: The diary table. The CHECK keeps ``provenance`` inside the allowed
#: vocabulary at the database level; the seam assigns the value and this is the
#: part that actually refuses anything else.
DIARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS diary (
    id INTEGER PRIMARY KEY,
    body TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT 'imported',
    created_at TEXT NOT NULL,
    CHECK (provenance IN ('manual', 'imported'))
)
"""


def open_diary(path: str) -> sqlite3.Connection:
    """Open the diary database file, creating it (and its schema) if needed."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(DIARY_SCHEMA)
    return conn


def _write_entry(db: sqlite3.Connection, payload: Mapping[str, Any], provenance: str) -> int:
    """Insert one diary row carrying the provenance the calling path assigns."""
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("diary body is required and must be a non-empty string")
    created_at = payload.get("created_at") or datetime.now(timezone.utc).isoformat()
    cursor = db.execute(
        "INSERT INTO diary (body, provenance, created_at) VALUES (?, ?, ?)",
        (body, provenance, created_at),
    )
    db.commit()
    return int(cursor.lastrowid)


def add_manual_entry(db: sqlite3.Connection, payload: Mapping[str, Any]) -> int:
    """Insert one diary entry as a manual (human-written) entry.

    The explicit counterpart of :func:`upsert_entry`: it is the only path that
    may assign ``provenance="manual"``, and it assigns that itself rather than
    reading it from the payload -- a manual entry is a human decision, not
    something an import (or any other caller) could claim.
    """
    return _write_entry(db, payload, PROVENANCE_MANUAL)


def upsert_entry(db: sqlite3.Connection, payload: Mapping[str, Any]) -> int:
    """Insert one diary entry through the import seam, assigning provenance here.

    The payload carries the entry's ``body`` and may carry a ``created_at``; a
    ``provenance`` it claims is read only to refuse it. An import is always
    ``imported``, so a payload claiming ``manual`` -- or any other value that is
    not an allowed import provenance -- is rejected here instead of being stored
    under a provenance it does not deserve. A clean (or absent) claim lands as
    ``imported``, and who wrote an entry is decided by the explicit path, not by
    whoever supplied the data.

    Values are bound as parameters, never interpolated into the SQL text.

    Returns the new row's ``id``.
    """
    claimed = payload.get("provenance")
    if claimed is not None and claimed not in IMPORT_ALLOWED_PROVENANCES:
        # Fixed, non-echoing refusal: the message names the constraint only. The
        # claimed value is caller-influenced input, so it is never interpolated
        # into -- or repr'd through -- the error text: no payload value, no raw
        # input, no echoed claim.
        raise VocabularyError("provenance value not permitted")
    return _write_entry(db, payload, IMPORTED_PROVENANCE)
