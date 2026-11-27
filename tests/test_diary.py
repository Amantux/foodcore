"""The diary's 'Log again' row: slot rendering, the one-tap write, the 'Logged' confirmation."""
from datetime import date, datetime, timedelta

from foodcore.diary import (
    LOG_AGAIN_LIMIT,
    LogAgainRow,
    LogToast,
    log_again_write,
    logged_after_write,
)
from foodcore.store import add_entry, get_entries, get_top_used, init_db, record_use

USER = "user-a"
TODAY = "2026-01-01"
_NOW = datetime(2026, 1, 1, 12, 0, 0)


class _Undo:
    """A stand-in for the handler that takes back the just-logged entry."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return True


def _row(*entries: tuple[str, str, float], today: str = TODAY) -> LogAgainRow:
    """A row built from ``(entry, meal, kcal)`` triples — the task-1 ranking shape."""
    top_used = [
        {"entry": entry, "meal": meal, "kcal": kcal}
        for (entry, meal, kcal) in entries
    ]
    return LogAgainRow.for_top_used(top_used, today=today)


# --- the row: rendering --------------------------------------------------------


def test_the_log_again_limit_is_the_top_five_window() -> None:
    assert LOG_AGAIN_LIMIT == 5


def test_row_renders_the_top_used_entries_best_first() -> None:
    row = _row(("oats", "breakfast", 300.0), ("toast", "breakfast", 180.0))

    assert len(row.chips) == LOG_AGAIN_LIMIT
    assert row.chip_at(0).entry == "oats"
    assert row.chip_at(0).meal == "breakfast"
    assert row.chip_at(0).kcal == 300.0
    assert row.chip_at(1).entry == "toast"
    assert row.chip_at(1).kcal == 180.0
    assert all(not chip.is_add for chip in row.chips if chip.entry is not None)


def test_row_fills_remaining_slots_with_the_search_first_add_chip() -> None:
    row = _row(("2 eggs + toast", "lunch", 300.0))

    assert len(row.chips) == LOG_AGAIN_LIMIT
    assert not row.chip_at(0).is_add
    assert [chip.is_add for chip in row.chips[1:]] == [True] * (LOG_AGAIN_LIMIT - 1)
    assert len(row.add_chips) == LOG_AGAIN_LIMIT - 1


def test_row_never_offers_more_than_the_limit() -> None:
    entries = [(f"entry-{index}", "meal", 100.0) for index in range(1, 9)]
    top_used = [{"entry": e, "meal": m, "kcal": k} for (e, m, k) in entries]

    row = LogAgainRow.for_top_used(top_used)

    assert len(row.chips) == LOG_AGAIN_LIMIT
    assert all(not chip.is_add for chip in row.chips)


def test_row_defaults_to_todays_entry() -> None:
    row = LogAgainRow.for_top_used([{"entry": "oats", "meal": "breakfast", "kcal": 300.0}])

    assert row.today == date.today().isoformat()


# --- the one-tap write ---------------------------------------------------------


def test_one_tap_write_writes_todays_entry_through_the_upsert_path(tmp_path) -> None:
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_entry(conn, USER, TODAY, "lunch", "2 eggs + toast", 300, "mom cooked")
    record_use(conn, USER, "2 eggs + toast", "lunch", 300, at="2026-01-01T12:00:00")

    row = _row(("2 eggs + toast", "lunch", 450.0))
    chip = row.chip_at(0)

    assert not chip.is_add
    assert log_again_write(conn, USER, row, chip) is True

    rows = get_entries(conn, USER, date=TODAY, meal="lunch")
    assert len(rows) == 1  # the re-log replaced the slot rather than duplicating
    assert rows[0]["kcal"] == 450.0


def test_one_tap_write_bumps_the_last_used_roll(tmp_path) -> None:
    conn = init_db(str(tmp_path / "diary.sqlite"))
    record_use(conn, USER, "oats", "breakfast", 300, at="2026-01-01T07:00:00")

    row = _row(("oats", "breakfast", 300.0))

    assert log_again_write(conn, USER, row, row.chip_at(0)) is True
    top = get_top_used(conn, USER)
    assert len(top) == 1
    assert top[0]["use_count"] == 2


def test_one_tap_write_on_an_add_slot_is_refused(tmp_path) -> None:
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_entry(conn, USER, TODAY, "lunch", "2 eggs + toast", 300, "mom cooked")

    row = _row(("2 eggs + toast", "lunch", 300.0))
    add_chip = row.chip_at(1)

    assert add_chip.is_add
    assert log_again_write(conn, USER, row, add_chip) is False
    assert len(get_entries(conn, USER, date=TODAY)) == 1


# --- the post-log 'Logged' toast: summary, undo, auto-expiry --------------------


def test_the_log_toast_auto_expires_after_the_window() -> None:
    toast = LogToast.after_log("Logged: 2 eggs + toast", now=_NOW)

    assert not toast.is_expired(_NOW)
    assert toast.is_expired(_NOW + timedelta(seconds=10))
    assert toast.is_expired(_NOW + timedelta(seconds=11))


def test_the_log_toast_without_undo_keeps_the_entry_in_place() -> None:
    toast = LogToast.after_log("Logged: 2 eggs + toast", now=_NOW)

    assert toast.undo is None
    assert toast.confirm(_NOW) is False


# --- the 'Logged' confirmation: after the one-tap write covers the slot --------


def test_the_logged_confirmation_appears_after_a_one_tap_write(tmp_path) -> None:
    """After the tap's write lands, the home shows the 'Logged' confirmation."""
    conn = init_db(str(tmp_path / "diary.sqlite"))
    row = _row(("2 eggs + toast", "lunch", 450.0))
    undo = _Undo()

    toast = logged_after_write(conn, USER, row, row.chip_at(0), undo=undo, now=_NOW)

    assert toast is not None
    assert toast.summary == "Logged: 2 eggs + toast"
    assert toast.undo is undo
    assert not toast.is_expired(_NOW)
    assert toast.confirm(_NOW) is True
    assert undo.calls == 1


def test_the_one_tap_write_covers_the_slot_so_the_confirmation_fires(tmp_path) -> None:
    """The upsert covers today's slot; the confirmation names that slot."""
    conn = init_db(str(tmp_path / "diary.sqlite"))
    row = _row(("2 eggs + toast", "lunch", 450.0))

    assert log_again_write(conn, USER, row, row.chip_at(0)) is True
    rows = get_entries(conn, USER, date=TODAY, meal="lunch")
    assert len(rows) == 1
    assert rows[0]["entry"] == "2 eggs + toast"
    assert rows[0]["kcal"] == 450.0

    toast = logged_after_write(conn, USER, row, row.chip_at(0), now=_NOW)
    assert isinstance(toast, LogToast)
    assert toast is not None
    assert toast.summary == "Logged: 2 eggs + toast"


def test_the_logged_confirmation_is_scoped_to_the_day_the_write_landed_on(tmp_path) -> None:
    """The 'Logged' confirmation is for the day the one-tap write landed on."""
    conn = init_db(str(tmp_path / "diary.sqlite"))
    row = _row(("2 eggs + toast", "lunch", 450.0), today="2026-01-02")

    toast = logged_after_write(conn, USER, row, row.chip_at(0), now=_NOW)

    assert toast is not None
    assert get_entries(conn, USER, date="2026-01-02", meal="lunch")
    assert get_entries(conn, USER, date=TODAY, meal="lunch") == []


def test_the_logged_confirmation_is_none_for_the_search_first_add_slot(tmp_path) -> None:
    """An add slot never writes, so it never gets a 'Logged' confirmation."""
    conn = init_db(str(tmp_path / "diary.sqlite"))
    add_entry(conn, USER, TODAY, "lunch", "2 eggs + toast", 300, "mom cooked")

    row = _row(("2 eggs + toast", "lunch", 300.0))
    add_chip = row.chip_at(1)

    assert add_chip.is_add
    assert logged_after_write(conn, USER, row, add_chip, now=_NOW) is None
    assert len(get_entries(conn, USER, date=TODAY)) == 1
