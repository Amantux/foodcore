"""The diary seam: provenance is assigned here, never copied from the payload.

These tests run against a real SQLite diary file (via ``tmp_path``), not mocks --
the seam, the parameterised insert and the write itself are what is being proven.
"""
import logging
import sqlite3

import pytest

from foodcore.diary import (
    PROVENANCE_IMPORTED,
    PROVENANCE_MANUAL,
    add_manual_entry,
    open_diary,
    upsert_entry,
)
from foodcore.provenance import VocabularyError


@pytest.fixture
def diary_db(tmp_path):
    """A real diary database file, opened the way a host app would open one."""
    return open_diary(tmp_path / "diary.db")


def _provenance_of(db, entry_id: int) -> str:
    row = db.execute("SELECT provenance FROM diary WHERE id = ?", (entry_id,)).fetchone()
    assert row is not None, "the entry row should exist"
    return str(row["provenance"])


def _count(db) -> int:
    return int(db.execute("SELECT COUNT(*) AS n FROM diary").fetchone()["n"])


def test_import_claiming_manual_is_rejected_and_writes_nothing(diary_db):
    # MUTATION GUARD: without the seam refusing the claim, the payload's
    # provenance would be trusted and the entry would land as a manual one.
    with pytest.raises(VocabularyError) as exc:
        upsert_entry(diary_db, {"body": "Bought oats", "provenance": PROVENANCE_MANUAL})

    assert _count(diary_db) == 0
    # The refusal names the constraint; it must not echo the claimed value.
    assert PROVENANCE_MANUAL not in str(exc.value)


def test_import_claiming_an_unknown_provenance_is_rejected(diary_db):
    # Only an allowed import provenance may pass the seam; anything else the
    # payload claims is a manual attempt in disguise. The refusal is fixed: it
    # names the constraint and never echoes the claimed value or payload text.
    body = "Bought oats"
    raw_claim = "bogus"
    with pytest.raises(VocabularyError) as exc:
        upsert_entry(diary_db, {"body": body, "provenance": raw_claim})

    assert _count(diary_db) == 0
    message = str(exc.value)
    assert raw_claim not in message
    assert body not in message
    assert message == "provenance value not permitted"


def test_import_with_absent_provenance_lands_as_imported(diary_db):
    entry_id = upsert_entry(diary_db, {"body": "Bought oats"})

    assert _provenance_of(diary_db, entry_id) == PROVENANCE_IMPORTED


def test_import_with_imported_provenance_lands_as_imported(diary_db):
    entry_id = upsert_entry(diary_db, {"body": "Bought oats", "provenance": PROVENANCE_IMPORTED})

    assert _provenance_of(diary_db, entry_id) == PROVENANCE_IMPORTED


def test_manual_entries_come_only_from_the_explicit_manual_path(diary_db, caplog):
    # The manual path assigns provenance itself; a payload that carries a
    # provenance claim is overridden, never trusted. Pin that here so a seam
    # that copies payload['provenance'] cannot quietly land a claimed string.
    claimed = "bogus"  # an untrusted provenance string, e.g. smuggled via payload

    with caplog.at_level(logging.DEBUG, logger="foodcore.diary"):
        entry_id = add_manual_entry(
            diary_db, {"body": "Wrote it in the notebook", "provenance": claimed}
        )

    assert _provenance_of(diary_db, entry_id) == PROVENANCE_MANUAL
    row = diary_db.execute(
        "SELECT body, provenance FROM diary WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row is not None, "the entry row should exist"
    # The row carries the manual value the seam assigned, never the claim.
    assert str(row["provenance"]) == PROVENANCE_MANUAL
    assert claimed not in str(row["provenance"])
    # No log line may echo the payload's raw provenance string either.
    assert claimed not in caplog.text, "diary log output echoed a raw provenance"


def test_raw_sqlite_insert_with_disallowed_provenance_raises_integrity_error(diary_db):
    # The database-level CHECK is the backstop for writes that bypass the
    # import seam entirely: a provenance outside the allowed vocabulary is
    # refused by SQLite itself, against a real diary file.
    with pytest.raises(sqlite3.IntegrityError):
        diary_db.execute(
            "INSERT INTO diary (body, provenance, created_at) VALUES (?, ?, ?)",
            ("Bought oats", "bogus", "2026-11-26T12:00:00+00:00"),
        )
    diary_db.rollback()

    assert _count(diary_db) == 0


def test_raw_sqlite_insert_of_manual_is_permitted_by_the_db_but_not_by_the_seam(diary_db):
    # 'manual' IS inside the CHECK's vocabulary, so the database itself allows a
    # raw insert of it; the import seam is what refuses it. The two layers are
    # complementary: the CHECK rejects values outside the vocabulary, while the
    # seam rejects a value from inside the vocabulary being claimed through an
    # import -- so the seam, not the raw path, is the only route to a manual entry.
    cursor = diary_db.execute(
        "INSERT INTO diary (body, provenance, created_at) VALUES (?, ?, ?)",
        ("Bought oats", PROVENANCE_MANUAL, "2026-11-26T12:00:00+00:00"),
    )
    diary_db.commit()
    row = diary_db.execute(
        "SELECT provenance FROM diary WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    assert row is not None, "the raw insert should have landed"
    assert str(row["provenance"]) == PROVENANCE_MANUAL
    assert _count(diary_db) == 1

    # The seam refuses the same claim, so nothing may reach the diary as a manual
    # entry through an import path -- even though the raw write was allowed here.
    with pytest.raises(ValueError):
        upsert_entry(diary_db, {"body": "Bought oats", "provenance": PROVENANCE_MANUAL})


def test_no_log_line_leaks_entry_body_or_raw_provenance(diary_db, caplog):
    """No log/trace line may echo the entry body or a raw provenance string.

    The diary seam assigns provenance itself, so nothing it emits may carry the
    entry's body text or a provenance claim beyond the allowed enum values
    (``'manual'`` / ``'imported'``). The seam does not log today; this asserts the
    absence of such lines through the import path -- a future log call that
    interpolated the payload body or a refused claim would trip it here.
    """
    body = "Bought oats"
    raw_claim = "bogus"  # a provenance value outside the allowed enum

    with caplog.at_level(logging.DEBUG, logger="foodcore.diary"):
        # The happy import path …
        upsert_entry(diary_db, {"body": body, "provenance": PROVENANCE_IMPORTED})
        # … and the refused claims. A refusal is exactly the moment a log line
        # would be most tempted to narrate the offending payload.
        with pytest.raises(ValueError):
            upsert_entry(diary_db, {"body": body, "provenance": PROVENANCE_MANUAL})
        with pytest.raises(ValueError):
            upsert_entry(diary_db, {"body": body, "provenance": raw_claim})

    assert body not in caplog.text, "diary log output echoed the entry body"
    assert raw_claim not in caplog.text, "diary log output echoed a raw provenance"
