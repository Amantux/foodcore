"""Round-trip tests for the diary store: seed -> import -> day totals, then add/edit/delete."""

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


def test_seeded_csv_import_then_per_day_kcal_totals(conn):
    """The committed sample CSV seeds a fresh store, and the day totals are the SUM over its rows."""
    assert db.import_csv(FIXTURE, db=conn) == 4

    # Per-day kcal totals over the seeded rows:
    #   2026-11-25 -> Oats with banana and peanut butter (420) + Turkey sandwich (540) = 960
    #   2026-11-26 -> Grilled salmon with vegetables (610)                       = 610
    #   2026-11-27 -> Herbal tea (NULL)                                          -> 0, not a guess
    assert db.day_totals(db=conn) == {
        "2026-11-25": 960.0,
        "2026-11-26": 610.0,
        "2026-11-27": 0.0,
    }


def test_add_edit_delete_cycle_totals_reflect_the_remaining_rows(conn):
    """One full add -> edit -> delete cycle, and the day totals follow the rows."""
    assert db.import_csv(FIXTURE, db=conn) == 4
    seeded_totals = db.day_totals(db=conn)

    # add: a new eating occasion lands on an existing day and moves its total.
    entry_id = db.add_entry("2026-11-25", "Pizza with pepperoni", kcal=350.0, db=conn)
    assert db.day_totals(db=conn)["2026-11-25"] == 1310.0

    # edit: changing the title and kcal moves the total again.
    updated = db.update_entry(
        entry_id, {"title": "Pizza with pepperoni and mushrooms", "kcal": 425.0}, db=conn
    )
    assert updated is not None
    assert updated["title"] == "Pizza with pepperoni and mushrooms"
    assert updated["kcal"] == 425.0
    assert db.day_totals(db=conn)["2026-11-25"] == 1385.0

    # delete: the row is gone and the totals fall back to the seeded rows only.
    assert db.delete_entry(entry_id, db=conn) is True
    assert db.get_entry(entry_id, db=conn) is None
    assert db.day_totals(db=conn) == seeded_totals
