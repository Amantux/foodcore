"""The diary's 'Log again' row — one-tap re-log chips, best first, add filler.

The home / day view renders this row above the fold: a horizontally scrollable
strip of 'Log again' chips, at most ``LOG_AGAIN_LIMIT`` of them, taken from the
user's per-user last-used ranking. Each chip is a single tap that writes today's
entry — the same entry, with its own meal-time and quantity — through the
store's single writer path, so re-logging lands as an upsert on the log slot
instead of a duplicate, and bumps the last-used roll behind it.

When the user has fewer than ``LOG_AGAIN_LIMIT`` known entries the remaining row
slots are filled with the search-first add affordance: the add sheet opens with a
search field as its primary control, rather than logging a known entry.

The row owns the slots and the write; the host owns the scrolling and the tap.
That keeps the storage policy in one place and the rendering a thin choice.

Once the tap's write covers today's slot — the upsert lands, so today's slot now
has an entry for that meal-time — the home shows the 'Logged' confirmation for
that slot, minted by :func:`logged_after_write` from the write's outcome.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable, Mapping

from .store import add_entry, record_use

#: How many entries the 'Log again' row offers — the top of the per-user
#: last-used ranking, best first, and the whole window the row renders.
LOG_AGAIN_LIMIT = 5


@dataclass(frozen=True)
class LogAgainChip:
    """One slot of the 'Log again' row.

    An entry chip carries the entry text plus the meal-time and quantity the
    one-tap write lands on. A slot with no entry is the search-first add
    affordance: the host opens the add sheet with a search field instead of
    logging a known entry.
    """

    entry: str | None
    meal: str | None = None
    kcal: float | None = None

    @property
    def is_add(self) -> bool:
        """Whether this slot is the search-first add affordance."""
        return self.entry is None


@dataclass(frozen=True)
class LogAgainRow:
    """The 'Log again' row: the day it writes to, and its slots."""

    chips: tuple[LogAgainChip, ...]
    today: str

    @classmethod
    def for_top_used(
        cls,
        top_used: Iterable[Mapping[str, Any]],
        *,
        limit: int = LOG_AGAIN_LIMIT,
        today: str | None = None,
    ) -> "LogAgainRow":
        """Build the row from a top-used ranking, best first.

        ``top_used`` is the task-1 query's answer — most recently used first,
        already capped at ``limit``. The row renders those entries and fills the
        remaining slots with the search-first add chip, so a strip always offers
        ``limit`` affordances and never fewer.
        """
        chips = tuple(
            LogAgainChip(entry=row["entry"], meal=row["meal"], kcal=row["kcal"])
            for row in top_used
        )[:limit]
        while len(chips) < limit:
            chips = chips + (LogAgainChip(entry=None, meal=None, kcal=None),)
        return cls(chips=chips, today=today if today is not None else date.today().isoformat())

    @property
    def add_chips(self) -> tuple[LogAgainChip, ...]:
        """The row slots that are the search-first add affordance."""
        return tuple(chip for chip in self.chips if chip.is_add)

    def chip_at(self, index: int) -> LogAgainChip:
        """The slot at ``index`` — the render reads slots off the row."""
        return self.chips[index]


def log_again_write(
    conn: sqlite3.Connection,
    user_id: str,
    row: LogAgainRow,
    chip: LogAgainChip,
) -> bool:
    """One-tap write for a tapped chip, through the store's single writer path.

    The write lands on ``row.today`` with the chip's own meal-time and quantity,
    via :func:`foodcore.store.add_entry` — the upsert on the log slot — and bumps
    the last-used roll. Returns ``True`` when an entry was written, ``False``
    when the slot is the search-first add affordance, in which case the host
    opens the add sheet with a search field instead of logging.
    """
    if chip.is_add or chip.entry is None or chip.meal is None or chip.kcal is None:
        return False
    add_entry(conn, user_id, row.today, chip.meal, chip.entry, chip.kcal, "")
    record_use(conn, user_id, chip.entry, chip.meal, chip.kcal)
    return True


#: How long the post-log 'Logged' confirmation stays on screen before it
#: auto-expires, in seconds.
TOAST_WINDOW_SECONDS = 10

#: The one-tap Undo: take back the just-logged entry. Returns whether it went through.
UndoHandler = Callable[[], bool]


@dataclass(frozen=True)
class LogToast:
    """The transient 'Logged' confirmation shown after a successful log."""

    summary: str
    undo: UndoHandler | None
    expires_at: datetime

    @classmethod
    def after_log(
        cls,
        summary: str,
        *,
        undo: UndoHandler | None = None,
        window_seconds: int = TOAST_WINDOW_SECONDS,
        now: datetime | None = None,
    ) -> "LogToast":
        """Mint the post-log 'Logged' confirmation for a successful log.

        ``summary`` is the logged line the user sees, e.g. ``"Logged: 2 eggs + toast"``.
        """
        moment = now if now is not None else datetime.now()
        return cls(summary=summary, undo=undo, expires_at=moment + timedelta(seconds=window_seconds))

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


def logged_after_write(
    conn: sqlite3.Connection,
    user_id: str,
    row: LogAgainRow,
    chip: LogAgainChip,
    *,
    undo: UndoHandler | None = None,
    window_seconds: int = TOAST_WINDOW_SECONDS,
    now: datetime | None = None,
) -> LogToast | None:
    """One-tap log that ends in the 'Logged' confirmation for today's slot.

    The tap writes through :func:`log_again_write` — the upsert on the log slot —
    so a ``True`` return means today's slot is covered and the write landed. When
    it did, mint the transient 'Logged' confirmation for that slot via
    :meth:`LogToast.after_log` and return it for the home to render; ``None``
    means the slot was the search-first add affordance, so no entry was written
    and there is nothing logged to confirm.
    """
    if not log_again_write(conn, user_id, row, chip) or chip.entry is None:
        return None
    return LogToast.after_log(
        f"Logged: {chip.entry}",
        undo=undo,
        window_seconds=window_seconds,
        now=now,
    )
