"""The diary CSV importer — reads files, writes through the store's writer.

The store owns every write to the ``entries`` table and owns the source
vocabulary that table defends (``manual`` | ``imported``). This module is the
file-facing half of that deal: it reads a CSV and hands each data row to
:func:`foodcore.store.add_entry` with ``source="imported"`` — hard-coded here,
because the CSV format carries no source column of its own and the provenance
of an imported row is a fact about the *act* of import, not about the row.

It owns no SQL of its own (never constructs a statement, never touches a cursor)
and no connection of its own (the caller passes in the connection it got from
:func:`foodcore.store.init_db`). Whatever a CSV row claims, this path can only
ever write ``imported`` — there is no way to steer it toward ``manual``,
``generated`` or ``planned``, and the store is the single place that could.
"""
from __future__ import annotations

import csv
import sqlite3

from . import store

__all__ = ("import_csv",)


def import_csv(conn: sqlite3.Connection, path: str) -> int:
    """Import the diary CSV at ``path`` through the store's single writer.

    The CSV's header row is ``date,meal,kcal,note`` and nothing more — there is
    deliberately no source column; an entry written here is always stamped
    ``source="imported"``.

    Returns the number of rows written. A data row with a blank required field
    or an unparseable ``kcal`` is skipped, not counted. A row whose
    ``(date, meal)`` primary key is already present is treated as already
    imported — the collision is absorbed as a no-op rather than an overwrite,
    so re-importing the same file is safe and idempotent.

    :param conn: the connection from :func:`foodcore.store.init_db`; the caller
        owns it from here on.
    :param path: filesystem path to the diary CSV.
    :return: how many rows this call actually wrote to the table.
    """
    written = 0
    with open(path, "r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for index, row in enumerate(reader):
            if index == 0:
                # Header row: date,meal,kcal,note. Never a data row.
                continue
            fields = list(row) + [""] * max(0, 4 - len(row))
            date = fields[0].strip()
            meal = fields[1].strip()
            kcal_raw = fields[2].strip()
            note = fields[3].strip()
            if not date or not meal or not kcal_raw:
                # A blank required field means the row is not importable.
                continue
            try:
                kcal = float(kcal_raw)
            except ValueError:
                # An unparseable kcal means the row is not importable.
                continue
            try:
                store.add_entry(conn, date, meal, kcal, note, source="imported")
            except sqlite3.IntegrityError:
                # PRIMARY KEY (date, meal) already holds this day/meal: it was
                # already imported, so treat the collision as a no-op. Never
                # overwrite — the existing row, and its provenance, stand.
                continue
            written += 1
    return written
