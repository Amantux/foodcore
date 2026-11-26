"""The end-to-end purge receipt lifecycle: full delete -> receipt -> fail-closed -> re-export tombstone."""
import json
import sqlite3

import pytest

from foodcore.diary_export import (
    DIARY_EXPORT_EMPTY_STATE,
    DIARY_EXPORT_SCHEMA_VERSION,
    DIARY_EXPORT_TOMBSTONE_KEY,
    export_diary,
)
from foodcore.purge import (
    DIARY_PURGE_TABLES,
    DiaryPurgeError,
    full_delete,
)

_ENTRIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entries (
    entry_id TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    food TEXT NOT NULL,
    portion TEXT NOT NULL,
    slot TEXT NOT NULL,
    notes TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version TEXT NOT NULL
);
"""

_PENDING_EXPORT = "diary-export.json"


def _seed_diary(db_path: str) -> None:
    """The fixture diary: one entry plus one row in each derived store."""
    conn = sqlite3.connect(db_path)
    conn.executescript(_ENTRIES_SCHEMA)
    for table in DIARY_PURGE_TABLES:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (entry_id TEXT PRIMARY KEY)")
        conn.execute(f"INSERT INTO {table} (entry_id) VALUES ('e1')")
    conn.execute(
        "INSERT INTO entries (entry_id, day, food, portion, slot, notes, provenance, "
        "created_at, updated_at, schema_version) VALUES "
        "('e1', '2026-11-26', 'rice, cooked', '1 cup', 'dinner', '', 'manual', "
        "'2026-11-26T10:00:00', '2026-11-26T10:00:00', '1')"
    )
    conn.commit()
    conn.close()


def _receipts(result) -> dict:
    return {receipt.store: receipt for receipt in result.receipts}


def test_full_delete_to_receipt_to_tombstoned_reexport_end_to_end(tmp_path):
    """The delete -> receipt -> re-export chain, over the whole store inventory."""
    db_path = str(tmp_path / "diary.db")
    dest = tmp_path / "diary-export.json"
    pending = tmp_path / _PENDING_EXPORT
    pending.write_text('{"schemaVersion": 1, "entries": []}', encoding="utf-8")
    _seed_diary(db_path)

    before = export_diary(db_path, dest)
    assert before["entries"]
    assert DIARY_EXPORT_TOMBSTONE_KEY not in before

    result = full_delete(db_path, pending_export_paths=[pending])

    # full delete -> receipt shown: every store cleared and verified empty, so the
    # delete completed and the receipt is the proof that was surfaced.
    assert result.ok is True
    by_store = _receipts(result)
    expected_stores = (
        {"diary"}
        | {f"diary.{table}" for table in DIARY_PURGE_TABLES}
        | {"diary.pending_exports"}
    )
    assert set(by_store) == expected_stores

    entries_receipt = by_store["diary"]
    assert entries_receipt.ok is True
    assert entries_receipt.verified_empty is True
    assert entries_receipt.rows_removed == 1
    assert "entries" in entries_receipt.verification_query

    for table in DIARY_PURGE_TABLES:
        receipt = by_store[f"diary.{table}"]
        assert receipt.ok is True
        assert receipt.verified_empty is True
        assert receipt.rows_removed == 1

    pending_receipt = result.receipts[-1]
    assert pending_receipt.store == "diary.pending_exports"
    assert pending_receipt.ok is True
    assert pending_receipt.verified_empty is True
    assert pending_receipt.rows_removed == 1
    assert _PENDING_EXPORT in pending_receipt.verification_query
    assert not pending.exists()

    conn = sqlite3.connect(db_path)
    for table in ("entries",) + DIARY_PURGE_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    conn.close()

    # re-export tombstone: the export after the purge is explicitly empty.
    document = export_diary(db_path, dest)
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded == document
    assert loaded["schemaVersion"] == DIARY_EXPORT_SCHEMA_VERSION
    assert loaded["entries"] == []
    assert set(loaded) == {"schemaVersion", "entries", DIARY_EXPORT_TOMBSTONE_KEY}
    assert loaded[DIARY_EXPORT_TOMBSTONE_KEY] == {"state": DIARY_EXPORT_EMPTY_STATE}
    assert "rice" not in dest.read_text(encoding="utf-8")


def test_a_full_delete_that_cannot_clear_fails_closed_before_the_reexport_tombstones(tmp_path):
    """Fail closed: the delete is not complete, so the re-export keeps the entries."""
    db_path = str(tmp_path / "diary.db")
    dest = tmp_path / "diary-export.json"
    _seed_diary(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TRIGGER refuse_delete BEFORE DELETE ON entries "
        "BEGIN SELECT RAISE(ABORT, 'refuse'); END"
    )
    conn.commit()
    conn.close()

    with pytest.raises(DiaryPurgeError) as excinfo:
        full_delete(db_path)

    assert "diary" in str(excinfo.value)
    assert excinfo.value.failing_stores == ("diary",)

    # Fail closed means the delete did NOT complete, so the next export is the
    # entries document, not the tombstone - the diary keeps telling the truth.
    document = export_diary(db_path, dest)
    assert len(document["entries"]) == 1
    assert DIARY_EXPORT_TOMBSTONE_KEY not in document
