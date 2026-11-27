"""The diary store: CHECK-constrained source and the single writer path."""
import sqlite3

import pytest

import foodcore.store as store
from foodcore.store import add_entry, add_imported, get_entries, init_db

#: Sources that exist in no host's vocabulary — yet must be refused loudly.
BAD_SOURCES = ("recommender", "planned")


def test_check_constraint_rejects_sources_outside_the_vocabulary(tmp_path):
    """A raw connection (bypassing the module) cannot write a bad source."""
    path = str(tmp_path / "diary.sqlite")
    conn = init_db(path)
    conn.close()

    raw = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO entries VALUES "
                "('2026-01-01','lunch',300,'x','recommender','2026-01-01T00:00:00')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO entries VALUES "
                "('2026-01-01','lunch',300,'x','planned','2026-01-01T00:00:00')"
            )
    finally:
        raw.close()


def test_add_entry_rejects_source_outside_the_vocabulary_before_sql(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    for bad in BAD_SOURCES:
        with pytest.raises(ValueError):
            add_entry(conn, "2026-01-01", "lunch", 300, "x", source=bad)
    # The refusal must happen before any SQL runs, so nothing was written.
    assert get_entries(conn) == []


def test_add_entry_defaults_to_manual_and_stamps_created_at(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_entry(conn, "2026-01-01", "lunch", 300, "mom cooked")
    rows = get_entries(conn, date="2026-01-01", meal="lunch")
    assert len(rows) == 1
    assert rows[0]["source"] == "manual"
    assert rows[0]["created_at"]


def test_add_imported_stamps_the_imported_source(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_imported(conn, "2026-01-01", "lunch", 300, "recipe: 300 kcal")
    rows = get_entries(conn, date="2026-01-01", meal="lunch")
    assert len(rows) == 1
    assert rows[0]["source"] == "imported"
    assert rows[0]["created_at"]


def test_module_exposes_no_generic_write_helpers():
    for name in ("add_entry", "add_imported", "init_db"):
        assert name in store.__all__
    generic = ("insert", "update", "exec", "execute", "executemany", "replace", "upsert", "delete")
    assert not (set(store.__all__) & set(generic))
    for name in generic:
        assert not hasattr(store, name), f"foodcore.store must not expose {name!r}"
