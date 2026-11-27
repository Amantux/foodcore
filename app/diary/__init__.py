"""The diary — user entries that carry their provenance.

An entry here is a fact about the user's own day, and like every value foodcore
stores it carries provenance: ``manual`` when a person wrote it, ``imported``
when it arrived through an import. The provenance is a closed vocabulary (see
``foodcore.diary.store.PROVENANCES``) and the only way an entry is created or
updated is :meth:`EntryStore.upsert`, which validates it.

THE CONTRACT, in one line, at the seam that enforces it::

    the synced store only ever receives final entries with valid provenance;
    snapshots never cross.
"""
from __future__ import annotations

from .store import (
    ORIGINS,
    PROVENANCES,
    DiaryEntry,
    DiaryProvenanceError,
    EntryStore,
)


__all__ = [
    "DiaryEntry",
    "DiaryProvenanceError",
    "EntryStore",
    "ORIGINS",
    "PROVENANCES",
]
