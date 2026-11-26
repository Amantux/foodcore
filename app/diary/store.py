"""The diary write seam — the only way a diary entry is created or updated.

THE CONTRACT, in one line, at the seam that enforces it::

    the synced store only ever receives final entries with valid provenance;
    snapshots never cross.

Every diary write — log, edit, undo, re-log, import — goes through
:meth:`EntryStore.upsert`. The entry is built through the diary contract
(:mod:`foodcore.diary.contract`): :meth:`Entry.from_dict` builds the
:class:`Entry` from the persisted mapping and :meth:`Entry.to_dict` writes it
back, so this module never re-declares the entry shape by hand and the value it
stores is by construction one the contract accepts.

Provenance is the diary's closed vocabulary — :data:`PROVENANCE_VOCABULARY`,
``manual`` | ``imported`` — and the contract's :class:`Entry` refuses anything
outside that set with :class:`foodcore.provenance.VocabularyError` before the
write is allowed to land.

The store is durable: the final entries live in a small SQLite table keyed by
entry id, and every write is serialised through the contract's own serializer
before it lands, so a later process reads back what an earlier one wrote.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Mapping, Optional

from .contract import PROVENANCE_VOCABULARY, Entry


class EntryStore:
    """The single write path for diary entries.

    Two stores live behind it, and they are never confused:

    * the **synced** store, which holds final entries;
    * the **device-local** undo snapshot space, which holds only provisional
      local state.

    A device-local snapshot is not a final entry, so it never enters the synced
    store — see the contract above.

    The synced store keeps its final entries in a SQLite table keyed by entry
    id. The caller names the backing file; every entry is serialised through the
    contract before it is written, and a fresh store opened on the same file
    reads the entries back. With no backing file named, the store keeps its
    table in this process's own memory.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        #: The backing file for the final diary entries, or ``None`` to keep the
        #: table in this process's memory.
        self._path = Path(path) if path is not None else None
        self._local = threading.local()
        self._synced: dict[str, Entry] = {}

        connection = self._connect()
        self._load(connection)

    @property
    def provenance_vocabulary(self) -> frozenset[str]:
        """The diary's closed provenance vocabulary (``manual`` | ``imported``)."""
        return PROVENANCE_VOCABULARY

    # -- plumbing ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        conn = sqlite3.connect(self._path if self._path is not None else ":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS diary_entry (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        conn.commit()
        self._local.conn = conn
        return conn

    def _load(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT id, payload FROM diary_entry").fetchall()
        for row in rows:
            entry = Entry.from_dict(json.loads(row["payload"]))
            self._synced[entry.id] = entry

    def _persist(self, entry: Entry) -> None:
        connection = self._connect()
        connection.execute(
            "INSERT OR REPLACE INTO diary_entry (id, payload) VALUES (?, ?)",
            (entry.id, json.dumps(entry.to_dict())),
        )
        connection.commit()

    # -- the write seam ----------------------------------------------------

    def upsert(self, data: Mapping[str, Any]) -> Entry:
        """Create or update the entry. The only diary write path that exists.

        ``data`` is the persisted entry shape; it is built into a :class:`Entry`
        through the contract's serializer and the contract's provenance CHECK
        (:func:`validate_provenance`) validates the result against
        :data:`PROVENANCE_VOCABULARY` before the write is stored.

        Returns the stored entry.
        """
        entry = Entry.from_dict(data)
        self._synced[entry.id] = entry
        self._persist(entry)
        return entry

    def get(self, entry_id: str) -> Optional[Entry]:
        """The final synced entry for ``entry_id``, if there is one."""
        return self._synced.get(entry_id)
