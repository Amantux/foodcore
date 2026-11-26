"""The purge sweep - clear every diary store, with a verified receipt."""
import sqlite3

import pytest

from foodcore.purge import (
    DIARY_PURGE_ENTRIES_TABLE,
    DIARY_PURGE_TABLES,
    DiaryPurgeError,
    PurgeStore,
    full_delete,
    purge_diary,
    purge_sweep,
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


def _seed_diary(db_path: str, *, with_derived: bool = True) -> None:
    """Build the fixture diary data the audit found: entries + derived stores."""
    conn = sqlite3.connect(db_path)
    conn.executescript(_ENTRIES_SCHEMA)
    if with_derived:
        for table in DIARY_PURGE_TABLES:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} (entry_id TEXT PRIMARY KEY)"
            )
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


def test_purge_sweep_clears_every_diary_store_and_returns_the_receipt(tmp_path):
    db_path = str(tmp_path / "diary.db")
    _seed_diary(db_path)
    result = purge_diary(db_path)

    assert result.ok is True
    by_store = _receipts(result)
    assert set(by_store) == {"diary"} | {f"diary.{t}" for t in DIARY_PURGE_TABLES}

    entries = by_store["diary"]
    assert entries.ok is True
    assert entries.verified_empty is True
    assert entries.rows_removed == 1
    assert "entries" in entries.verification_query

    for table in DIARY_PURGE_TABLES:
        receipt = by_store[f"diary.{table}"]
        assert receipt.ok is True
        assert receipt.verified_empty is True
        assert receipt.rows_removed == 1

    conn = sqlite3.connect(db_path)
    for table in ("entries",) + DIARY_PURGE_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    conn.close()


def test_the_sweep_is_not_clean_when_a_store_fails_verification():
    store = PurgeStore(
        name="diary.boom",
        clear=lambda: 0,
        verify=lambda: False,
        verification_query="SELECT count(*) AS n FROM boom",
    )

    result = purge_sweep([store])

    assert result.ok is False
    assert len(result.receipts) == 1
    receipt = result.receipts[0]
    assert receipt.store == "diary.boom"
    assert receipt.ok is False
    assert receipt.verified_empty is False
    assert receipt.rows_removed == 0
    assert receipt.verification_query == "SELECT count(*) AS n FROM boom"


def _verify_that_raises() -> bool:
    raise RuntimeError("the verification exploded")


def test_a_store_whose_verify_raises_is_recorded_failed_and_the_sweep_continues():
    """A verify() failure is recorded in the receipt and the sweep keeps going."""
    failing = PurgeStore(
        name="diary.boom",
        clear=lambda: 0,
        verify=_verify_that_raises,
        verification_query="SELECT count(*) AS n FROM boom",
    )
    healthy = PurgeStore(
        name="diary.good",
        clear=lambda: 0,
        verify=lambda: True,
        verification_query="SELECT count(*) AS n FROM good",
    )

    result = purge_sweep([failing, healthy])

    assert result.ok is False
    by_store = _receipts(result)
    failed_receipt = by_store["diary.boom"]
    assert failed_receipt.store == "diary.boom"
    assert failed_receipt.ok is False
    assert failed_receipt.verified_empty is False
    assert failed_receipt.rows_removed == 0
    assert failed_receipt.verification_query == "SELECT count(*) AS n FROM boom"
    # The sweep did not stop at the failing store: later stores were still purged.
    assert by_store["diary.good"].ok is True


def test_a_store_that_cannot_clear_makes_the_sweep_not_clean(tmp_path):
    db_path = str(tmp_path / "diary.db")
    _seed_diary(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TRIGGER refuse_delete BEFORE DELETE ON entries "
        "BEGIN SELECT RAISE(ABORT, 'refuse'); END"
    )
    conn.commit()
    conn.close()

    result = purge_diary(db_path)

    assert result.ok is False
    failing = [r for r in result.receipts if not r.ok]
    assert [r.store for r in failing] == ["diary"]
    # The partial failure stays observable: the other stores were still swept.
    cleared = {r.store for r in result.receipts if r.ok}
    assert cleared == {f"diary.{t}" for t in DIARY_PURGE_TABLES}


def test_pending_export_files_are_purged_and_reported(tmp_path):
    export = tmp_path / "diary-export.json"
    export.write_text('{"schemaVersion": 1, "entries": []}')

    result = purge_diary(str(tmp_path / "diary.db"), pending_export_paths=[export])

    assert result.ok is True
    receipt = result.receipts[-1]
    assert receipt.store == "diary.pending_exports"
    assert receipt.ok is True
    assert receipt.verified_empty is True
    assert receipt.rows_removed == 1
    assert "diary-export.json" in receipt.verification_query
    assert not export.exists()


def test_full_delete_completes_and_surfaces_the_receipt(tmp_path):
    """The full delete is complete only when every store verifies empty."""
    db_path = str(tmp_path / "diary.db")
    _seed_diary(db_path)

    result = full_delete(db_path)

    # Clean receipt: the delete completed and the receipt is the surfaced proof.
    assert result.ok is True
    by_store = _receipts(result)
    assert set(by_store) == {"diary"} | {f"diary.{t}" for t in DIARY_PURGE_TABLES}
    for receipt in result.receipts:
        assert receipt.ok is True
        assert receipt.verified_empty is True
    assert by_store["diary"].rows_removed == 1
    for table in DIARY_PURGE_TABLES:
        assert by_store[f"diary.{table}"].rows_removed == 1

    conn = sqlite3.connect(db_path)
    for table in ("entries",) + DIARY_PURGE_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    conn.close()


def test_full_delete_fails_closed_and_names_the_failing_store(tmp_path):
    """A store that cannot be verified empty fails the delete closed, naming it."""
    db_path = str(tmp_path / "diary.db")
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

    # Fail closed: the delete is not complete, and the failing store is named.
    assert "diary" in str(excinfo.value)
    assert excinfo.value.failing_stores == ("diary",)


def test_full_delete_reports_the_failed_store_and_does_not_claim_success(
    monkeypatch, tmp_path
):
    """A verify() failure fails the full delete closed, naming the failed store."""
    db_path = str(tmp_path / "diary.db")
    _seed_diary(db_path)

    def _verify_raises_for_entries(db_path: str, table: str) -> bool:
        if table == DIARY_PURGE_ENTRIES_TABLE:
            raise RuntimeError("the verification exploded")
        return True

    monkeypatch.setattr("foodcore.purge._table_is_empty", _verify_raises_for_entries)

    with pytest.raises(DiaryPurgeError) as excinfo:
        full_delete(db_path)

    # Fail closed: the delete did not complete, and the failed store is named.
    assert "diary" in str(excinfo.value)
    assert excinfo.value.failing_stores == ("diary",)


def test_a_malicious_derived_table_name_is_refused_before_anything_is_purged(tmp_path):
    """A derived table name that is not a strict diary identifier is refused.

    Fail closed: the full delete never reaches a verdict, and nothing is purged.
    """
    db_path = str(tmp_path / "diary.db")
    _seed_diary(db_path)

    with pytest.raises(ValueError, match="not a valid diary table identifier"):
        full_delete(db_path, derived_tables=["entries; DROP TABLE entries"])

    # Fail closed: nothing was purged, so the diary keeps its entries.
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT count(*) FROM entries").fetchone()[0] == 1
    conn.close()


@pytest.mark.parametrize(
    "malicious",
    [
        "entries; DROP TABLE entries",
        "x y",
        "1abc",
    ],
)
def test_derived_table_names_must_be_strict_identifiers(tmp_path, malicious):
    """Only strict diary identifiers may be used as purge table names."""
    with pytest.raises(ValueError, match="not a valid diary table identifier"):
        purge_diary(str(tmp_path / "diary.db"), derived_tables=[malicious])


def test_a_legitimate_derived_table_name_still_purges(tmp_path):
    """A strict, diary-owned derived table name is purged as before."""
    db_path = str(tmp_path / "diary.db")
    _seed_diary(db_path)

    result = purge_diary(db_path, derived_tables=list(DIARY_PURGE_TABLES))

    assert result.ok is True
    by_store = _receipts(result)
    for table in DIARY_PURGE_TABLES:
        receipt = by_store[f"diary.{table}"]
        assert receipt.ok is True
        assert receipt.verified_empty is True
        assert receipt.rows_removed == 1
