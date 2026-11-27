"""The diary store: CHECK-constrained source and the single writer path."""
import sqlite3

import pytest

import foodcore.store as store
from foodcore.store import (
    add_entry,
    add_imported,
    get_entries,
    get_top_used,
    init_db,
    record_use,
)

#: Sources that exist in no host's vocabulary — yet must be refused loudly.
BAD_SOURCES = ("recommender", "planned")

#: The user the diary tests write under.
USER = "user-a"


def test_check_constraint_rejects_sources_outside_the_vocabulary(tmp_path):
    """A raw connection (bypassing the module) cannot write a bad source."""
    path = str(tmp_path / "diary.sqlite")
    conn = init_db(path)
    conn.close()

    raw = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO entries "
                "(user_id, date, meal, entry, kcal, note, source, created_at) "
                "VALUES ('user-a','2026-01-01','lunch','2 eggs + toast',300,'x',"
                "'recommender','2026-01-01T00:00:00')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO entries "
                "(user_id, date, meal, entry, kcal, note, source, created_at) "
                "VALUES ('user-a','2026-01-01','lunch','2 eggs + toast',300,'x',"
                "'planned','2026-01-01T00:00:00')"
            )
    finally:
        raw.close()


def test_add_entry_rejects_source_outside_the_vocabulary_before_sql(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    for bad in BAD_SOURCES:
        with pytest.raises(ValueError):
            add_entry(
                conn,
                USER,
                "2026-01-01",
                "lunch",
                "2 eggs + toast",
                300,
                "x",
                source=bad,
            )
    # The refusal must happen before any SQL runs, so nothing was written.
    assert get_entries(conn, USER) == []


def test_add_entry_defaults_to_manual_and_stamps_created_at(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_entry(conn, USER, "2026-01-01", "lunch", "2 eggs + toast", 300, "mom cooked")
    rows = get_entries(conn, USER, date="2026-01-01", meal="lunch")
    assert len(rows) == 1
    assert rows[0]["source"] == "manual"
    assert rows[0]["created_at"]


def test_add_imported_stamps_the_imported_source(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_imported(conn, USER, "2026-01-01", "lunch", "2 eggs + toast", 300, "recipe: 300 kcal")
    rows = get_entries(conn, USER, date="2026-01-01", meal="lunch")
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


def test_record_use_counts_uses_and_stamps_the_last_used_at(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    record_use(conn, "user-a", "2 eggs + toast", "breakfast", 350, at="2026-01-01T08:00:00")
    record_use(conn, "user-a", "2 eggs + toast", "breakfast", 350, at="2026-01-01T12:30:00")

    top = get_top_used(conn, "user-a")
    assert len(top) == 1
    assert top[0]["use_count"] == 2
    assert top[0]["last_used_at"] == "2026-01-01T12:30:00"
    assert top[0]["meal"] == "breakfast"
    assert top[0]["kcal"] == 350.0


def test_top_used_returns_the_most_recently_used_first(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    record_use(conn, "user-a", "dinner", "dinner", 500, at="2026-01-01T18:00:00")
    record_use(conn, "user-a", "lunch", "lunch", 300, at="2026-01-01T12:00:00")

    top = get_top_used(conn, "user-a")
    assert [row["meal"] for row in top] == ["dinner", "lunch"]


def test_top_used_breaks_ties_by_recency(tmp_path):
    """Equal use counts tie — the more recently used entry ranks first."""
    conn = init_db(str(tmp_path / "diary.sqlite"))
    record_use(conn, "user-a", "oats", "breakfast", 300, at="2026-01-01T07:30:00")
    record_use(conn, "user-a", "eggs + toast", "breakfast", 150, at="2026-01-01T07:00:00")

    top = get_top_used(conn, "user-a")
    assert [row["entry"] for row in top] == ["oats", "eggs + toast"]


def test_top_used_returns_at_most_five_entries(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    for index, entry in enumerate(["eggs", "oats", "toast", "fruit", "coffee", "soup"], start=1):
        record_use(conn, "user-a", entry, "meal", 100, at=f"2026-01-0{index}T08:00:00")

    top = get_top_used(conn, "user-a")
    assert len(top) == 5
    assert [row["entry"] for row in top] == ["soup", "coffee", "fruit", "toast", "oats"]


def test_top_used_returns_fewer_than_limit_when_the_user_has_few(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    record_use(conn, "user-a", "2 eggs + toast", "breakfast", 150, at="2026-01-01T07:00:00")

    top = get_top_used(conn, "user-a", limit=5)
    assert len(top) == 1
    assert top[0]["entry"] == "2 eggs + toast"


def test_top_used_is_scoped_to_one_user(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    record_use(conn, "user-a", "eggs", "breakfast", 150, at="2026-01-01T07:00:00")
    record_use(conn, "user-b", "pizza", "dinner", 900, at="2026-01-01T19:00:00")

    assert [row["entry"] for row in get_top_used(conn, "user-a")] == ["eggs"]
    assert [row["entry"] for row in get_top_used(conn, "user-b")] == ["pizza"]


# --- the slot write: upsert on (day, meal-time, entry) --------------------


def test_first_write_to_a_slot_creates_the_row(tmp_path):
    """A write to a slot that has never been written creates it."""
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_entry(conn, USER, "2026-01-01", "lunch", "2 eggs + toast", 300, "mom cooked")

    rows = get_entries(conn, USER, date="2026-01-01", meal="lunch")
    assert len(rows) == 1
    assert rows[0]["entry"] == "2 eggs + toast"
    assert rows[0]["kcal"] == 300.0
    assert rows[0]["source"] == "manual"
    assert rows[0]["created_at"]


def test_second_write_to_the_same_slot_replaces_the_prior_row(tmp_path):
    """Re-logging the same slot replaces the prior row — no duplicate."""
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_entry(conn, USER, "2026-01-01", "lunch", "2 eggs + toast", 300, "mom cooked")
    add_entry(conn, USER, "2026-01-01", "lunch", "2 eggs + toast", 450, "mom cooked double")

    rows = get_entries(conn, USER, date="2026-01-01", meal="lunch")
    assert len(rows) == 1
    assert rows[0]["kcal"] == 450.0
    assert rows[0]["note"] == "mom cooked double"
    assert rows[0]["source"] == "manual"
    assert rows[0]["created_at"]


def test_a_different_meal_time_is_a_new_slot_and_creates_a_new_row(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_entry(conn, USER, "2026-01-01", "lunch", "2 eggs + toast", 300, "mom cooked")
    add_entry(conn, USER, "2026-01-01", "dinner", "2 eggs + toast", 300, "mom cooked")

    rows = get_entries(conn, USER, date="2026-01-01")
    assert len(rows) == 2


def test_a_different_entry_is_a_new_slot_and_creates_a_new_row(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_entry(conn, USER, "2026-01-01", "lunch", "2 eggs + toast", 300, "mom cooked")
    add_entry(conn, USER, "2026-01-01", "lunch", "oats", 300, "mom cooked")

    rows = get_entries(conn, USER, date="2026-01-01", meal="lunch")
    assert len(rows) == 2


def test_the_slot_write_is_scoped_to_one_user(tmp_path):
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_entry(conn, "user-a", "2026-01-01", "lunch", "2 eggs + toast", 300, "mom cooked")
    add_entry(conn, "user-b", "2026-01-01", "lunch", "2 eggs + toast", 500, "dad cooked")

    assert len(get_entries(conn, "user-a", date="2026-01-01", meal="lunch")) == 1
    assert len(get_entries(conn, "user-b", date="2026-01-01", meal="lunch")) == 1
