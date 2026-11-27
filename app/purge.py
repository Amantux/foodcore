"""The purge sweep — clear every diary store, with a verified receipt.

The diary's personal data lives in the stores the audit found in
``docs/diary-store-audit.md``: the device-local entries database, the derived
tables kept alongside it — undo/redo snapshots, favourites, the last-used cache
— and the temp/pending export files a host app may keep.

The sweep clears each store and then verifies it came back empty, returning a
receipt per store::

    {"store": ..., "rows_removed": ..., "verification_query": ...,
     "verified_empty": ..., "ok": ...}

``rows_removed`` counts the rows purged, or the files removed for a file store.
``verification_query`` is the query that proved emptiness. ``verified_empty``
reports the store came back empty; ``ok`` reports the store was cleared and
verified. A store that did not clear cleanly, or that did not verify empty,
carries ``ok=False`` — the sweep is clean only when every store it ran verified
empty, so a delete is never reported complete off a store that could not be
verified.

Each store is cleared under its own transaction-ish sequence — one store, one
transaction, rolled back on failure — and the sweep keeps going afterwards, so a
partial failure stays observable in the receipts it returns. Nothing is cleared
silently: a store that fails is named, and the sweep's result is not clean.

Store names are strict diary identifiers: a caller-supplied table name is validated
against that shape and quoted (double-quote, escaped) before any statement is built
against it, so a name can never reach a statement as a fragment.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

__all__ = [
    "DIARY_PURGE_ENTRIES_TABLE",
    "DIARY_PURGE_TABLES",
    "DiaryPurgeError",
    "PurgeReceipt",
    "PurgeStore",
    "PurgeSweepResult",
    "full_delete",
    "purge_diary",
    "purge_sweep",
]

#: The entries table of the diary's entries database — the primary personal-data store.
DIARY_PURGE_ENTRIES_TABLE: str = "entries"

#: The derived tables the audit found the delete-side purge must clear, in purge order.
#: A derived table that does not exist yet is a no-op rather than a creation: the purge
#: clears what is there, it does not migrate.
DIARY_PURGE_TABLES: tuple[str, ...] = ("undo_snapshots", "favorites", "last_used")

#: The only table-name shape a diary purge statement may target: a strict ASCII
#: identifier - ``^[A-Za-z_][A-Za-z0-9_]*$`` - quoted before use.
_DIARY_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class PurgeStore:
    """One store the sweep clears, with how it clears and how it is verified."""

    name: str
    clear: Callable[[], int]
    verify: Callable[[], bool]
    verification_query: str = ""


@dataclass(frozen=True)
class PurgeReceipt:
    """One store's purge outcome, as carried by the sweep's receipt."""

    store: str
    rows_removed: int
    verification_query: str
    verified_empty: bool
    ok: bool


@dataclass(frozen=True)
class PurgeSweepResult:
    """The receipts of one sweep, and whether the sweep came back clean."""

    receipts: tuple[PurgeReceipt, ...]

    @property
    def ok(self) -> bool:
        """True only when every store the sweep ran verified empty."""
        return all(receipt.ok for receipt in self.receipts)


class DiaryPurgeError(Exception):
    """The diary full delete failed closed: a store did not verify empty.

    Raised by the full delete when the purge sweep came back with at least one
    store that did not verify empty. The delete is then NOT complete and must not
    be reported as done — the failing store(s) are named here so the user is told
    exactly what could not be proven empty, instead of a silent success.
    """

    def __init__(self, failing_stores: Sequence[str]) -> None:
        self.failing_stores = tuple(failing_stores)
        super().__init__(
            "the foodcore diary full delete failed closed; the following store(s) "
            f"could not be verified empty: {', '.join(self.failing_stores)}."
        )


def purge_sweep(stores: Iterable[PurgeStore]) -> PurgeSweepResult:
    """Clear each store, verify it emptied, and return the per-store receipts."""
    return PurgeSweepResult(receipts=tuple(_purge_store(store) for store in stores))


def _purge_store(store: PurgeStore) -> PurgeReceipt:
    try:
        rows_removed = store.clear()
    except Exception:
        # Best effort, never silent: a store that did not clear cleanly is a store
        # that did not verify empty, and the partial failure stays observable in
        # the receipt the sweep returns.
        return PurgeReceipt(
            store=store.name,
            rows_removed=0,
            verification_query=store.verification_query,
            verified_empty=False,
            ok=False,
        )
    try:
        verified_empty = bool(store.verify())
    except Exception:
        # The store cleared, but could not be verified empty - record that in the
        # receipt (verified_empty=False, ok=False) and let the sweep keep going: the
        # failure stays observable in the receipts, and the delete fails closed off
        # the not-clean receipt instead of aborting with an unverifiable store left
        # behind in the later stores of the sweep.
        verified_empty = False
    return PurgeReceipt(
        store=store.name,
        rows_removed=rows_removed,
        verification_query=store.verification_query,
        verified_empty=verified_empty,
        ok=verified_empty,
    )


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


def _quote_table(table: str) -> str:
    """Return ``table`` as a double-quoted SQL identifier, or refuse it.

    The diary's stores are named by the caller - the derived tables a host keeps
    alongside the entries database - so a name reaches a statement only once it has
    passed the strict diary-identifier shape. Anything else - a SQL fragment like
    ``"entries; DROP TABLE entries"``, a name with whitespace, a leading digit - is
    refused with a clear error before any statement is built against it.
    """
    if not isinstance(table, str) or _DIARY_TABLE_NAME.fullmatch(table) is None:
        raise ValueError(
            f"the diary table name {table!r} is not a valid diary table identifier; refusing to purge it."
        )
    return '"' + table.replace('"', '""') + '"'


def _purge_table(db_path: str, table: str) -> int:
    """Delete every row of one table under one transaction; return the purged count.

    One store, one transaction, rolled back on failure - best-effort atomicity.
    A table that does not exist is a no-op rather than a creation. The table name
    must be a strict diary identifier, so the statements below interpolate a
    validated, quoted identifier and nothing else.
    """
    quoted = _quote_table(table)
    conn = _connect(db_path)
    try:
        if not _table_exists(conn, table):
            return 0
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(f"SELECT count(*) AS n FROM {quoted}").fetchone()
        count = int(row[0]) if row is not None else 0
        if count:
            conn.execute(f"DELETE FROM {quoted}")
        conn.execute("COMMIT")
        return count
    except sqlite3.Error:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def _table_is_empty(db_path: str, table: str) -> bool:
    """The verification query's answer: is the table empty (absent means empty)?"""
    quoted = _quote_table(table)
    conn = _connect(db_path)
    try:
        if not _table_exists(conn, table):
            return True
        row = conn.execute(f"SELECT count(*) AS n FROM {quoted}").fetchone()
        return row is not None and int(row[0]) == 0
    finally:
        conn.close()


def _entries_purge_store(db_path: str) -> PurgeStore:
    """The diary entries database: clear and verify the entries table."""
    return PurgeStore(
        name="diary",
        clear=lambda: _purge_table(db_path, DIARY_PURGE_ENTRIES_TABLE),
        verify=lambda: _table_is_empty(db_path, DIARY_PURGE_ENTRIES_TABLE),
        verification_query=f"SELECT count(*) AS n FROM {DIARY_PURGE_ENTRIES_TABLE}",
    )


def _derived_purge_store(db_path: str, table: str) -> PurgeStore:
    """One derived diary store (undo snapshots, favourites, last-used cache)."""
    quoted = _quote_table(table)
    return PurgeStore(
        name=f"diary.{table}",
        clear=lambda: _purge_table(db_path, table),
        verify=lambda: _table_is_empty(db_path, table),
        verification_query=f"SELECT count(*) AS n FROM {quoted}",
    )


def _file_purge_store(name: str, paths: Sequence[str | Path]) -> PurgeStore:
    """One file-kind store (a temp/pending export file): clear and verify absent."""
    resolved = tuple(Path(path) for path in paths)

    def clear() -> int:
        removed = 0
        for path in resolved:
            if path.exists():
                path.unlink()
                removed += 1
        return removed

    def verify() -> bool:
        return all(not path.exists() for path in resolved)

    return PurgeStore(
        name=name,
        clear=clear,
        verify=verify,
        verification_query="; ".join(f"path {path} absent" for path in resolved),
    )


def purge_diary(
    entries_db_path: str,
    *,
    derived_tables: Sequence[str] = DIARY_PURGE_TABLES,
    pending_export_paths: Sequence[str | Path] = (),
) -> PurgeSweepResult:
    """Purge every diary store the audit found, and return the receipt.

    Enumerates the diary's stores - the entries database plus the derived
    tables the audit lists, and any temp/pending export files the caller names -
    clears each under its own transaction-ish sequence, and verifies each came
    back empty.

    The caller decides which derived tables and export files exist to purge; a
    derived table that is absent is a no-op rather than a creation, not a gap.
    """
    stores: list[PurgeStore] = [_entries_purge_store(entries_db_path)]
    for table in derived_tables:
        stores.append(_derived_purge_store(entries_db_path, table))
    if pending_export_paths:
        stores.append(_file_purge_store("diary.pending_exports", pending_export_paths))
    return purge_sweep(stores)


def full_delete(
    entries_db_path: str,
    *,
    derived_tables: Sequence[str] = DIARY_PURGE_TABLES,
    pending_export_paths: Sequence[str | Path] = (),
) -> PurgeSweepResult:
    """The full delete: purge every diary store, verify, and only then complete.

    The delete-all control hands the whole diary to the purge sweep — the entries
    database, the derived tables the host keeps alongside it, and any temp/pending
    export files the caller names — and turns the sweep's receipt into the delete's
    verdict.

    When every store verified empty the delete is complete and the receipt is
    returned, to be shown to the user as the proof of what was removed. When any
    store failed to clear or to verify, the delete fails closed: :class:`DiaryPurgeError`
    names the store(s) that could not be verified empty, and the delete is not
    reported complete — never silently succeed, never report success off a store
    that could not be verified.
    """
    result = purge_diary(
        entries_db_path,
        derived_tables=derived_tables,
        pending_export_paths=pending_export_paths,
    )
    if result.ok:
        # Clean receipt: every store verified empty, so the delete is complete and
        # the receipt is the proof to surface before it is reported done.
        return result
    failing = tuple(
        sorted({receipt.store for receipt in result.receipts if not receipt.ok})
    )
    raise DiaryPurgeError(failing)
