"""The diary export — the tombstoned, zero-entry document after a purge."""
import json
import sqlite3

from foodcore.diary_export import (
    DIARY_EXPORT_DOCUMENT_KEYS,
    DIARY_EXPORT_EMPTY_STATE,
    DIARY_EXPORT_ENTRY_KEYS,
    DIARY_EXPORT_SCHEMA_VERSION,
    DIARY_EXPORT_TOMBSTONE_KEY,
    export_diary,
)
from foodcore.purge import full_delete

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

_ENTRY = (
    "INSERT INTO entries (entry_id, day, food, portion, slot, notes, provenance, "
    "created_at, updated_at, schema_version) VALUES "
    "('e1', '2026-11-26', 'rice, cooked', '1 cup', 'dinner', '', 'manual', "
    "'2026-11-26T10:00:00', '2026-11-26T10:00:00', '1')"
)


def _seed_diary(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(_ENTRIES_SCHEMA)
    conn.execute(_ENTRY)
    conn.commit()
    conn.close()


def test_export_before_the_purge_writes_the_entries(tmp_path):
    db_path = str(tmp_path / "diary.db")
    dest = tmp_path / "diary-export.json"
    _seed_diary(db_path)

    document = export_diary(db_path, dest)
    loaded = json.loads(dest.read_text(encoding="utf-8"))

    assert loaded == document
    assert set(loaded) == {"schemaVersion", "entries"}
    assert loaded["schemaVersion"] == DIARY_EXPORT_SCHEMA_VERSION
    assert len(loaded["entries"]) == 1
    assert loaded["entries"][0]["entryId"] == "e1"
    assert loaded["entries"][0]["food"] == "rice, cooked"
    assert loaded["entries"][0]["schemaVersion"] == DIARY_EXPORT_SCHEMA_VERSION
    assert DIARY_EXPORT_TOMBSTONE_KEY not in loaded


def test_the_export_document_is_closed_against_unknown_keys():
    assert set(DIARY_EXPORT_DOCUMENT_KEYS) == {
        "schemaVersion",
        "entries",
        DIARY_EXPORT_TOMBSTONE_KEY,
    }
    assert set(DIARY_EXPORT_ENTRY_KEYS) == {
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


def test_the_export_of_an_absent_entries_table_is_the_tombstoned_empty_document(tmp_path):
    db_path = str(tmp_path / "diary.db")
    dest = tmp_path / "diary-export.json"

    document = export_diary(db_path, dest)

    assert document["entries"] == []
    assert set(document) == {"schemaVersion", "entries", DIARY_EXPORT_TOMBSTONE_KEY}
    assert document[DIARY_EXPORT_TOMBSTONE_KEY] == {"state": DIARY_EXPORT_EMPTY_STATE}


def test_export_after_the_purge_is_tombstoned_and_empty(tmp_path):
    db_path = str(tmp_path / "diary.db")
    dest = tmp_path / "diary-export.json"
    _seed_diary(db_path)

    before = export_diary(db_path, dest)
    assert before["entries"]

    result = full_delete(db_path)
    assert result.ok is True

    document = export_diary(db_path, dest)
    loaded = json.loads(dest.read_text(encoding="utf-8"))

    assert loaded == document
    assert loaded["schemaVersion"] == DIARY_EXPORT_SCHEMA_VERSION
    assert loaded["entries"] == []
    # the tombstone marker is explicit, and the diary is clearly empty
    assert set(loaded) == {"schemaVersion", "entries", DIARY_EXPORT_TOMBSTONE_KEY}
    assert loaded[DIARY_EXPORT_TOMBSTONE_KEY] == {"state": DIARY_EXPORT_EMPTY_STATE}
    # no stale content survives into the purged export
    assert "rice" not in dest.read_text(encoding="utf-8")


def test_no_stale_snapshot_or_cache_can_resurrect_a_purged_record(tmp_path):
    db_path = str(tmp_path / "diary.db")
    dest = tmp_path / "diary-export.json"
    _seed_diary(db_path)
    full_delete(db_path)

    # A stale derived store — an undo snapshot, a cache — must not be read back
    # as if it were the diary's live content.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS undo_snapshots (entry_id TEXT PRIMARY KEY)"
    )
    conn.execute("INSERT INTO undo_snapshots (entry_id) VALUES ('e1')")
    conn.commit()
    conn.close()

    document = export_diary(db_path, dest)

    assert document["entries"] == []
    assert DIARY_EXPORT_TOMBSTONE_KEY in document
    assert "rice" not in dest.read_text(encoding="utf-8")
