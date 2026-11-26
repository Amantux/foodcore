"""The diary — user food entries and the contract they are written against.

An entry here is a fact about the user's own day, and like every value
foodcore stores it carries provenance: ``manual`` when a person wrote it,
``imported`` when it arrived through an importer.

The shape of an entry and the closed provenance vocabulary live in
:mod:`foodcore.diary.contract` — the one versioned contract module — and
nothing else in this package re-declares them, so the write seam, the storage
``CHECK`` and the undo snapshots all agree on the shape instead of drifting.
"""
from __future__ import annotations

from .contract import (
    CONTRACT_VERSION,
    SNAPSHOT_VERSION,
    DiaryFood,
    Entry,
    PROVENANCE_VOCABULARY,
    UndoSnapshot,
)
from .store import EntryStore

__all__ = [
    "CONTRACT_VERSION",
    "SNAPSHOT_VERSION",
    "DiaryFood",
    "Entry",
    "PROVENANCE_VOCABULARY",
    "UndoSnapshot",
    "EntryStore",
]
