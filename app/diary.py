"""The diary's transient toast and inline edit sheet.

After a successful log the diary shows a transient toast that carries the logged
summary and an Undo control. The toast is time-boxed: it auto-expires after
``TOAST_WINDOW_SECONDS`` and once it has expired the just-logged entry is left
exactly as it was written -- an Undo that arrives late, or is never used, keeps
the entry in place.

The toast owns the window and the undo control; the destructive step -- taking
back the just-logged entry -- is delegated to a handler supplied by the component
that owns the entries, bound to the recent-entry pointer the successful log
minted. That split keeps the removal next to the storage it may remove while the
toast stays a small, clock-driven piece of state that a host renders and a user
acts on.

Only the last logged entry is ever undoable. Each successful log mints a fresh
recent-entry pointer and a fresh undo handler; no history is kept, so an Undo can
only ever take back the entry it was minted for.

Tapping a logged entry opens the diary's small inline edit sheet -- not a full
page -- with controls for the entry's quantity, meal slot and time, plus Save and
Delete actions.

Like the toast, the sheet owns the draft the controls edit and the actions the
user can take; the writes are delegated to handlers supplied by the component
that owns the entries. Saving persists the edited entry through the host's
upsert; deleting removes the entry being edited.

No schema change: the owning session keeps the sheet's state in memory and the
storage keeps whatever writes it receives.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

#: How long the post-log toast stays on screen before it auto-expires, in seconds.
TOAST_WINDOW_SECONDS = 10

#: The label of the Undo control the toast renders.
UNDO_LABEL = "Undo"

#: The label of the Save control the edit sheet renders.
SAVE_LABEL = "Save"

#: The label of the Delete control the edit sheet renders.
DELETE_LABEL = "Delete"

#: The one-tap Undo: take back the just-logged entry. Returns whether it went through.
UndoHandler = Callable[[], bool]


@dataclass(frozen=True)
class LogEntry:
    """A diary entry: the day, meal slot, quantity and note.

    Plain in-memory data rather than a schema change: the owning session keeps it
    as the recent-entry pointer for undo or as the draft of the inline edit sheet,
    and nothing persists it.
    """

    day: str
    meal: str
    kcal: float
    note: str | None = None


#: The one-tap Save: persist the edited diary entry. Returns whether it went through.
SaveHandler = Callable[[LogEntry], bool]

#: The one-tap Delete: take back the diary entry being edited. Returns whether it went through.
DeleteHandler = Callable[[], bool]


def undo_handler_for(
    entry: LogEntry,
    *,
    remove: Callable[[LogEntry], bool],
) -> UndoHandler:
    """Mint the one-tap Undo handler that takes back the just-logged ``entry``.

    The handler closes over the recent-entry pointer and delegates the actual
    removal -- or restoration, should a host prefer to restore rather than drop --
    to ``remove``, the storage-facing callable of the component that owns the
    entries. The toast's auto-expiry window is enforced by the toast itself before
    it ever reaches the handler.
    """

    def _undo() -> bool:
        return bool(remove(entry))

    return _undo


def save_handler_for(
    *,
    save: Callable[[LogEntry], bool],
) -> SaveHandler:
    """Mint the one-tap Save handler that persists an edited diary entry.

    The handler takes the edited entry the user saved -- the sheet's draft once the
    quantity, meal slot and time controls have been applied -- and delegates the
    write to ``save``, the storage-facing upsert of the component that owns the
    entries. The diary owns no schema of its own, so persisting an edit is the
    host's upsert and nothing more: saving an edited entry may mint a fresh write
    when the edit moves it to another day or meal slot.
    """

    def _save(entry: LogEntry) -> bool:
        return bool(save(entry))

    return _save


def delete_handler_for(
    entry: LogEntry,
    *,
    remove: Callable[[LogEntry], bool],
) -> DeleteHandler:
    """Mint the one-tap Delete handler that takes back the diary entry being edited.

    The handler closes over the entry being edited and delegates the removal to
    ``remove``, the storage-facing callable of the component that owns the
    entries.
    """

    def _delete() -> bool:
        return bool(remove(entry))

    return _delete


@dataclass(frozen=True)
class LogToast:
    """The transient toast shown after a successful log."""

    summary: str
    undo: UndoHandler | None
    expires_at: datetime
    entry: LogEntry | None = None
    undo_label: str = UNDO_LABEL

    @classmethod
    def after_log(
        cls,
        summary: str,
        *,
        entry: LogEntry | None = None,
        undo: UndoHandler | None = None,
        window_seconds: int = TOAST_WINDOW_SECONDS,
        now: datetime | None = None,
        undo_label: str = UNDO_LABEL,
    ) -> "LogToast":
        """Mint the post-log toast for a successful log.

        ``summary`` is the logged line the user sees, e.g. ``"Logged: 2 eggs + toast"``.
        ``entry`` is the just-logged entry recorded as the toast's recent-entry
        pointer, and ``undo`` is the handler the rendered Undo control taps -- it
        is what removes or restores that entry.
        """
        moment = now if now is not None else datetime.now()
        return cls(
            summary=summary,
            undo=undo,
            expires_at=moment + timedelta(seconds=window_seconds),
            entry=entry,
            undo_label=undo_label,
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        """Whether the toast's auto-expiry window has elapsed."""
        moment = now if now is not None else datetime.now()
        return moment >= self.expires_at

    def confirm(self, now: datetime | None = None) -> bool:
        """Apply the Undo the user tapped, honouring the auto-expiry window.

        Returns True when the just-logged entry was undone; False when there was
        nothing to undo (no handler, or the window had elapsed) -- in which case
        the entry is left exactly as it was written.
        """
        if self.undo is None or self.is_expired(now):
            return False
        return bool(self.undo())


@dataclass(frozen=True)
class EditSheet:
    """The small inline edit sheet shown when a logged entry is tapped for editing.

    The sheet owns the entry being edited and the draft the user's controls left --
    quantity, meal slot and time -- plus the Save and Delete actions the user can
    take on it. Like the post-log toast, the writes are delegated to handlers
    supplied by the component that owns the entries, so the sheet stays a small,
    renderable piece of state that a host turns into controls and a user acts on.

    The sheet is an inline sheet, not a full page, and keeps no history of edits:
    the draft is the entry as the controls left it, and dismissing without saving
    throws the draft away with it.
    """

    entry: LogEntry
    draft: LogEntry
    save: SaveHandler | None = None
    delete: DeleteHandler | None = None
    save_label: str = SAVE_LABEL
    delete_label: str = DELETE_LABEL

    @classmethod
    def for_editing(
        cls,
        entry: LogEntry,
        *,
        save: SaveHandler | None = None,
        delete: DeleteHandler | None = None,
        save_label: str = SAVE_LABEL,
        delete_label: str = DELETE_LABEL,
    ) -> "EditSheet":
        """Open the inline edit sheet for ``entry``.

        ``save`` persists whatever edited entry the user saved, ``delete`` takes
        back ``entry``, and the sheet renders the given Save / Delete labels.
        """
        return cls(
            entry=entry,
            draft=entry,
            save=save,
            delete=delete,
            save_label=save_label,
            delete_label=delete_label,
        )

    def edited_entry(self) -> LogEntry:
        """The entry as the sheet's quantity, meal slot and time controls left it."""
        return self.draft

    def save_edits(self) -> bool:
        """Persist the sheet's draft over the entry being edited.

        Returns True when the edits went through; False when there was no save
        control to tap, in which case the entry is left exactly as it was written.
        """
        if self.save is None:
            return False
        return bool(self.save(self.draft))

    def delete_entry(self) -> bool:
        """Delete the entry being edited.

        Returns True when the entry was taken back; False when there was no delete
        control to tap.
        """
        if self.delete is None:
            return False
        return bool(self.delete())
