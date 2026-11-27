"""Smoke tests for the diary store: the table exists, the constraints hold."""

import os
import sqlite3

import pytest

from foodcore.diary import db

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sample.csv")


@pytest.fixture()
def conn(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "diary.db"))
    db.init_db(conn)
    yield conn
    conn.close()


def _table_names(conn) -> "set[str]":
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def test_init_db_creates_only_the_entries_table(conn):
    assert _table_names(conn) == {"entries"}


def test_add_get_and_list_roundtrip(conn):
    entry_id = db.add_entry("2026-11-25", "Dinner", kind="meal", kcal=600.0, db=conn)

    row = db.get_entry(entry_id, db=conn)
    assert row is not None
    assert row["title"] == "Dinner"
    assert row["kind"] == "meal"
    assert row["kcal"] == 600.0

    entries = db.list_entries(db=conn)
    assert [entry["id"] for entry in entries] == [entry_id]


def test_list_entries_are_newest_first(conn):
    older = db.add_entry("2026-11-24", "Lunch", kcal=500.0, db=conn)
    newer = db.add_entry("2026-11-25", "Dinner", kcal=700.0, db=conn)

    entries = db.list_entries(db=conn)
    assert [entry["id"] for entry in entries] == [newer, older]


def test_update_entry_writes_only_the_given_fields(conn):
    entry_id = db.add_entry("2026-11-25", "Dinner", kcal=600.0, db=conn)

    updated = db.update_entry(entry_id, {"kcal": 650.0, "title": "Feast"}, db=conn)
    assert updated is not None
    assert updated["kcal"] == 650.0
    assert updated["title"] == "Feast"
    assert updated["when"] == "2026-11-25"


def test_delete_entry_removes_the_row(conn):
    entry_id = db.add_entry("2026-11-25", "Dinner", db=conn)

    assert db.delete_entry(entry_id, db=conn) is True
    assert db.get_entry(entry_id, db=conn) is None
    assert db.delete_entry(entry_id, db=conn) is False


def test_day_totals_sum_kcal_per_day_ignoring_nulls(conn):
    db.add_entry("2026-11-25", "Breakfast", kcal=300.0, db=conn)
    db.add_entry("2026-11-25", "Lunch", kcal=400.0, db=conn)
    db.add_entry("2026-11-26", "Dinner", kcal=500.0, db=conn)
    db.add_entry("2026-11-26", "Snack", kcal=None, db=conn)

    assert db.day_totals(db=conn) == {"2026-11-25": 700.0, "2026-11-26": 500.0}


def test_day_totals_counts_an_all_null_day_as_zero(conn):
    db.add_entry("2026-11-27", "Tea", kcal=None, db=conn)

    assert db.day_totals(db=conn) == {"2026-11-27": 0.0}


def test_kind_must_be_meal_or_food(conn):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_entry("2026-11-25", "Snack", kind="bogus", db=conn)


def test_source_must_be_manual_or_imported(conn):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_entry("2026-11-25", "Snack", source="gps", db=conn)


def test_import_csv_loads_the_committed_fixture(conn):
    """The committed sample fixture imports cleanly and lands as source='imported'."""
    assert db.import_csv(FIXTURE, db=conn) == 4

    entries = db.list_entries(db=conn)
    assert len(entries) == 4
    assert all(entry["source"] == "imported" for entry in entries)
    assert all(entry["kind"] == "food" for entry in entries)

    # The row with an empty kcal cell lands as NULL, not as a guess.
    unmeasured = [entry for entry in entries if entry["title"] == "Herbal tea"]
    assert len(unmeasured) == 1
    assert unmeasured[0]["kcal"] is None


def test_imported_entries_come_back_newest_first(conn):
    db.import_csv(FIXTURE, db=conn)

    entries = db.list_entries(db=conn)
    assert [entry["when"] for entry in entries] == [
        "2026-11-27T08:05:00",
        "2026-11-26T18:30:00",
        "2026-11-25T12:15:00",
        "2026-11-25T08:30:00",
    ]


def test_import_csv_requires_the_exact_header(tmp_path):
    bad = tmp_path / "diary.csv"
    bad.write_text("when,title,kcal,source\n2026-11-25T08:30:00,Oats,420\n", encoding="utf-8")
    with pytest.raises(ValueError):
        db.import_csv(bad, db=conn)
