"""The diary write seam — the only way an entry is created or updated.

THE CONTRACT, in one line, at the seam that enforces it::

    the synced store only ever receives final entries with valid provenance;
    snapshots never cross.

Every diary write — log, edit, undo, re-log, import — goes through
:meth:`EntryStore.upsert`. That is the single write path, so provenance gets
stamped in exactly one place, the device-local undo snapshot can never be
mistaken for final state, and a value outside the diary's closed CHECK enum is
refused before it can be stored and later mistaken for a real entry.

Provenance is the diary's closed vocabulary — ``manual`` (the user wrote the
entry) or ``imported`` (it arrived through an import). It is validated against
that set here, at this trust boundary, and anything else is refused with
:class:`DiaryProvenanceError`, which is a ``ValueError``.

Origin is orthogonal to provenance. ``device-local`` writes take the
device-local undo snapshot and leave the synced store alone; ``synced`` writes
are final and land in the synced store, purging the stale snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


#: The diary's closed CHECK enum: who wrote this entry. ``manual`` or
#: ``imported``; anything else is refused at the seam.
PROVENANCES: frozenset[str] = frozenset({"manual", "imported"})

#: Where a write is being acknowledged from: a provisional local write, or a
#: final, synced write.
ORIGINS: frozenset[str] = frozenset({"device-local", "synced"})


class DiaryProvenanceError(ValueError):
    """A diary entry was written with a provenance outside the CHECK enum."""


@dataclass(frozen=True)
class DiaryEntry:
    """One diary entry: its identity, its text, and the provenance stamped on it."""

    id: str
    text: str
    provenance: str

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, str) or self.provenance not in PROVENANCES:
            raise DiaryProvenanceError(
                f"diary provenance {self.provenance!r} is not one of: "
                f"{', '.join(sorted(PROVENANCES))}"
            )


class EntryStore:
    """The single write path for diary entries.

    Two stores live behind it, and they are never confused:

    * the **synced** store, which holds final entries;
    * the **device-local** undo snapshot space, which holds only provisional
      local state.

    A device-local snapshot is not a final entry, so it never enters the synced
    store — see the contract above.
    """

    def __init__(self) -> None:
        #: Final entries. Only ever receives final entries with valid provenance.
        self._synced: dict[str, DiaryEntry] = {}
        #: Device-local undo snapshots, keyed by entry id.
        self._snapshots: dict[str, DiaryEntry] = {}

    # ------------------------------------------------------------------
    # The seam — the only way an entry is created or updated
    # ------------------------------------------------------------------

    def upsert(
        self,
        entry: DiaryEntry,
        provenance: str,
        *,
        origin: str = "device-local",
    ) -> DiaryEntry:
        """Create or update the entry. The only diary write path that exists.

        ``entry`` is the content (id + text), and its carried ``provenance`` is
        the authoritative provenance for this write. ``provenance`` is the
        diary CHECK-enum value (``manual`` | ``imported``) this write is
        acknowledged with and must agree with ``entry.provenance``; a
        disagreement is refused rather than silently re-stamped. ``origin`` is
        where the write is happening from.

        Before overwriting an existing synced entry, the stored provenance is
        compared with the incoming entry's: a final entry whose provenance
        changes is a refused write, never a re-stamp.
        """
        entry_provenance = self._require_provenance(entry.provenance)
        stamped_provenance = self._require_provenance(provenance)
        if stamped_provenance != entry_provenance:
            raise DiaryProvenanceError(
                f"diary entry {entry.id!r} carries provenance {entry_provenance!r} "
                f"but this write was offered {stamped_provenance!r}; the entry's own "
                f"provenance is authoritative and the write is refused"
            )
        if origin not in ORIGINS:
            raise ValueError(
                f"diary origin {origin!r} is not one of: {', '.join(sorted(ORIGINS))}"
            )

        stamped = DiaryEntry(id=entry.id, text=entry.text, provenance=entry_provenance)

        if origin == "device-local":
            # Provisional local write: take the undo snapshot, leave the synced
            # store alone. Snapshots never cross into it.
            self._snapshots[entry.id] = stamped
            return stamped

        existing = self._synced.get(entry.id)
        if existing is not None and existing.provenance != entry_provenance:
            raise DiaryProvenanceError(
                f"refusing to overwrite diary entry {entry.id!r}: synced provenance is "
                f"{existing.provenance!r}, incoming provenance is {entry_provenance!r}"
            )

        # Final write: the synced store receives the stamped entry, and the
        # now-superseded device-local snapshot is purged.
        self._synced[entry.id] = stamped
        self._snapshots.pop(entry.id, None)
        return stamped

    # ------------------------------------------------------------------
    # Reads over the two stores
    # ------------------------------------------------------------------

    def get(self, entry_id: str) -> Optional[DiaryEntry]:
        """The final synced entry for ``entry_id``, if there is one."""
        return self._synced.get(entry_id)

    def snapshot(self, entry_id: str) -> Optional[DiaryEntry]:
        """The device-local undo snapshot for ``entry_id``, if there is one."""
        return self._snapshots.get(entry_id)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    @staticmethod
    def _require_provenance(provenance: str) -> str:
        if not isinstance(provenance, str) or provenance not in PROVENANCES:
            raise DiaryProvenanceError(
                f"diary provenance {provenance!r} is not one of: "
                f"{', '.join(sorted(PROVENANCES))}"
            )
        return provenance
