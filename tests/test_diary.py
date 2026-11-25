"""The diary's transient toast and inline edit sheet: summary, undo, save, delete."""
from datetime import datetime, timedelta

from foodcore.diary import (
    DELETE_LABEL,
    SAVE_LABEL,
    TOAST_WINDOW_SECONDS,
    UNDO_LABEL,
    EditSheet,
    LogEntry,
    LogToast,
    delete_handler_for,
    save_handler_for,
    undo_handler_for,
)

_NOW = datetime(2026, 1, 1, 12, 0, 0)


class _Undo:
    """A stand-in for the handler that takes back the just-logged entry."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return True


def test_after_log_mints_a_transient_toast_with_the_logged_summary_and_undo():
    undo = _Undo()
    toast = LogToast.after_log("Logged: 2 eggs + toast", undo=undo, now=_NOW)

    assert toast.summary == "Logged: 2 eggs + toast"
    assert toast.undo is undo
    assert toast.expires_at == _NOW + timedelta(seconds=TOAST_WINDOW_SECONDS)


def test_the_auto_expire_window_defaults_to_ten_seconds():
    toast = LogToast.after_log("Logged: 2 eggs + toast", undo=_Undo(), now=_NOW)

    assert toast.expires_at - _NOW == timedelta(seconds=TOAST_WINDOW_SECONDS)


def test_the_toast_auto_expires_after_the_window():
    undo = _Undo()
    toast = LogToast.after_log("Logged: 2 eggs + toast", undo=undo, now=_NOW)

    assert not toast.is_expired(_NOW)
    assert toast.is_expired(_NOW + timedelta(seconds=TOAST_WINDOW_SECONDS))
    assert toast.is_expired(_NOW + timedelta(seconds=TOAST_WINDOW_SECONDS + 1))


def test_undo_inside_the_window_takes_the_entry_back():
    undo = _Undo()
    toast = LogToast.after_log("Logged: 2 eggs + toast", undo=undo, now=_NOW)

    assert toast.confirm(_NOW) is True
    assert undo.calls == 1


def test_undo_after_the_window_keeps_the_entry_in_place():
    undo = _Undo()
    toast = LogToast.after_log("Logged: 2 eggs + toast", undo=undo, now=_NOW)

    assert toast.confirm(_NOW + timedelta(seconds=TOAST_WINDOW_SECONDS + 1)) is False
    assert undo.calls == 0


def test_an_undo_with_no_handler_keeps_the_entry_in_place():
    toast = LogToast.after_log("Logged: 2 eggs + toast", now=_NOW)

    assert toast.confirm(_NOW) is False


def test_after_log_records_the_just_logged_entry_as_the_recent_entry_pointer():
    """The just-logged entry is the toast's recent-entry pointer for the undo."""
    entry = LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note="mom cooked")
    toast = LogToast.after_log("Logged: pizza", entry=entry, now=_NOW)

    assert toast.entry is entry
    assert toast.undo is None


def test_the_toast_carries_the_undo_control_it_renders():
    plain = LogToast.after_log("Logged: 2 eggs + toast", now=_NOW)
    assert plain.undo_label == UNDO_LABEL
    assert plain.entry is None

    custom = LogToast.after_log(
        "Logged: 2 eggs + toast", undo=_Undo(), now=_NOW, undo_label="Not now"
    )
    assert custom.undo_label == "Not now"


def test_the_undo_handler_minted_for_a_log_takes_back_that_logs_just_logged_entry():
    entry = LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note="mom cooked")
    taken: list[LogEntry] = []

    def remove(target: LogEntry) -> bool:
        taken.append(target)
        return True

    toast = LogToast.after_log(
        "Logged: pizza",
        entry=entry,
        undo=undo_handler_for(entry, remove=remove),
        now=_NOW,
    )

    assert toast.confirm(_NOW) is True
    assert taken == [entry]


def test_tapping_undo_removes_the_just_logged_entry_from_the_diary():
    """Log -> tap Undo -> the just-logged entry is gone from the diary."""
    diary: list[LogEntry] = [
        LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note="mom cooked"),
    ]
    just_logged = LogEntry(day="2026-01-01", meal="lunch", kcal=500.0, note="pizza")
    diary.append(just_logged)

    def remove(target: LogEntry) -> bool:
        diary.remove(target)
        return True

    toast = LogToast.after_log(
        "Logged: pizza",
        entry=just_logged,
        undo=undo_handler_for(just_logged, remove=remove),
        now=_NOW,
    )

    assert toast.confirm(_NOW) is True
    assert just_logged not in diary
    assert diary == [LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note="mom cooked")]


def test_only_the_last_logged_entry_is_undoable():
    """The undo covers the just-logged entry; there is no deeper history to walk."""
    diary: list[LogEntry] = [LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note="mom cooked")]
    just_logged = LogEntry(day="2026-01-01", meal="dinner", kcal=500.0, note="pizza")
    diary.append(just_logged)

    def remove(target: LogEntry) -> bool:
        diary.remove(target)
        return True

    toast = LogToast.after_log(
        "Logged: pizza",
        entry=just_logged,
        undo=undo_handler_for(just_logged, remove=remove),
        now=_NOW,
    )

    assert toast.confirm(_NOW) is True
    assert just_logged not in diary
    # An earlier entry, if any, is left exactly as it was written.
    assert diary[0].note == "mom cooked"


def test_tapping_an_entry_opens_the_inline_edit_sheet_with_the_entry_as_draft():
    """Tap an entry -> the edit sheet opens carrying that entry as its draft."""
    entry = LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note="mom cooked")
    saved: list[LogEntry] = []

    def save(edited: LogEntry) -> bool:
        saved.append(edited)
        return True

    def remove(target: LogEntry) -> bool:
        return True

    sheet = EditSheet.for_editing(
        entry,
        save=save_handler_for(save=save),
        delete=delete_handler_for(entry, remove=remove),
    )

    assert sheet.entry is entry
    assert sheet.edited_entry() == entry
    assert sheet.save_label == SAVE_LABEL
    assert sheet.delete_label == DELETE_LABEL


def test_the_edit_sheet_draft_reflects_the_edited_quantity_meal_slot_and_time():
    """Changing quantity, meal slot or time shows up in the sheet's draft."""
    entry = LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note="mom cooked")
    edited = LogEntry(day="2026-01-02", meal="dinner", kcal=500.0, note=None)
    sheet = EditSheet(entry=entry, draft=edited)

    assert sheet.edited_entry() == edited


def test_saving_the_edit_sheet_persists_the_edited_entry():
    """Save -> the edited entry the user saved is what gets persisted."""
    entry = LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note="mom cooked")
    saved: list[LogEntry] = []

    def save(edited: LogEntry) -> bool:
        saved.append(edited)
        return True

    edited = LogEntry(day="2026-01-01", meal="dinner", kcal=500.0, note="pizza")
    sheet = EditSheet(entry=entry, draft=edited, save=save_handler_for(save=save))

    assert sheet.save_edits() is True
    assert saved == [edited]


def test_saving_without_a_save_control_keeps_the_entry_in_place():
    entry = LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note=None)
    sheet = EditSheet(entry=entry, draft=entry)

    assert sheet.save_edits() is False


def test_deleting_the_entry_being_edited_removes_it():
    """Delete -> the entry being edited is taken back."""
    entry = LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note="mom cooked")
    removed: list[LogEntry] = []

    def remove(target: LogEntry) -> bool:
        removed.append(target)
        return True

    sheet = EditSheet(
        entry=entry,
        draft=entry,
        delete=delete_handler_for(entry, remove=remove),
    )

    assert sheet.delete_entry() is True
    assert removed == [entry]


def test_deleting_without_a_delete_control_keeps_the_entry_in_place():
    entry = LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note=None)
    sheet = EditSheet(entry=entry, draft=entry)

    assert sheet.delete_entry() is False


def test_saving_the_edit_updates_the_diary_entry_and_deleting_removes_it():
    """The diary reflects an edit save, and a delete takes the entry back out."""
    diary: list[LogEntry] = [LogEntry(day="2026-01-01", meal="lunch", kcal=300.0, note="mom cooked")]

    edited = LogEntry(day="2026-01-01", meal="dinner", kcal=500.0, note="pizza")
    saved: list[LogEntry] = []
    removed: list[LogEntry] = []

    def save(target: LogEntry) -> bool:
        saved.append(target)
        diary[0] = target
        return True

    def remove(target: LogEntry) -> bool:
        removed.append(target)
        diary.remove(target)
        return True

    sheet = EditSheet(
        entry=diary[0],
        draft=edited,
        save=save_handler_for(save=save),
        delete=delete_handler_for(diary[0], remove=remove),
    )

    assert sheet.save_edits() is True
    assert saved == [edited]
    assert diary[0] == edited

    # After the save the stored entry is the edited one, so the delete takes that back.
    delete_sheet = EditSheet(
        entry=diary[0],
        draft=diary[0],
        delete=delete_handler_for(diary[0], remove=remove),
    )
    assert delete_sheet.delete_entry() is True
    assert removed == [edited]
    assert diary == []
