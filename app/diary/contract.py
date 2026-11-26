"""The diary entry contract — the one versioned schema for a diary entry.

Scope of this module: the shape of a diary entry and the closed vocabulary of
its provenance.

It is deliberately its own module, separate from the reference-data library
(:mod:`foodcore.provenance` describes a *reference* fact — a gram of flour weighed
against a USDA portion — while a diary entry is *user* data with its own lifecycle:
logged, edited, undone, imported). The separation is why it lives under
``diary/`` rather than next to the provenance module, and why it carries its own
version rather than borrowing the reference-data one.

The contract exists so the three places that would otherwise each hand-write the
same entry shape stop drifting:

* the write seam (:mod:`foodcore.diary.store`) stamps provenance from
  :data:`PROVENANCE_VOCABULARY`;
* the storage ``CHECK`` — :func:`validate_provenance`, which validates against
  that same vocabulary — refuses anything outside it;
* the undo snapshots serialise :class:`Entry` itself, wrapped in an
  :class:`UndoSnapshot` that carries :data:`SNAPSHOT_VERSION` alongside the
  entry.

``CONTRACT_VERSION`` versions this shape. It is bumped only when a change makes
the shape incompatible; additive changes keep the version.

``SNAPSHOT_VERSION`` versions the undo snapshot envelope that serialises an
:class:`Entry` — the entry shape plus the version field that travels alongside
it. It is bumped only when a change makes a snapshot unreadable; additive changes
keep the version.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..provenance import VocabularyError

__all__ = [
    "CONTRACT_VERSION",
    "SNAPSHOT_VERSION",
    "DiaryFood",
    "Entry",
    "PROVENANCE_VOCABULARY",
    "UndoSnapshot",
    "validate_provenance",
]


#: The diary's closed provenance vocabulary: ``manual`` — a person logged the
#: entry; ``imported`` — it arrived through an importer. The point of the set is
#: that no third kind exists, by design: not yet, and not by accident of a
#: typo'd write. The write seam, the storage ``CHECK`` and this module all read
#: the same set, so a value outside it is refused before it can be stored and
#: later mistaken for a real entry.
PROVENANCE_VOCABULARY: frozenset[str] = frozenset({"manual", "imported"})

#: The version of the diary entry shape implemented here. Bumped only on a
#: breaking change to the shape; additive changes keep it.
CONTRACT_VERSION = "1"

#: The schema version of an undo snapshot envelope (:class:`UndoSnapshot`). It
#: versions the snapshot — the contract-serialised entry plus the version field
#: that travels alongside it — rather than the entry shape alone, and is bumped
#: only on a breaking change to the snapshot shape; additive changes keep it.
SNAPSHOT_VERSION = "1"


def validate_provenance(value: object) -> str:
    """The diary's provenance CHECK: accept only values in the closed vocabulary.

    The allowed set is :data:`PROVENANCE_VOCABULARY` — the single source of truth
    for the diary's provenance, imported here rather than re-declared — so the
    write seam, the storage CHECK and this module all read the same set and a
    value outside it is refused before it can be stored and later mistaken for a
    real entry.
    """
    if not isinstance(value, str) or value not in PROVENANCE_VOCABULARY:
        raise VocabularyError(
            f"diary provenance {value!r} is not one of: "
            f"{', '.join(sorted(PROVENANCE_VOCABULARY))}"
        )
    return value


@dataclass(frozen=True)
class DiaryFood:
    """One food on a diary entry, with the quantity it was consumed at."""

    food: str
    quantity: float

    def __post_init__(self) -> None:
        if not str(self.food).strip():
            raise ValueError(
                "DiaryFood requires a food: an entry that names no food has "
                "nothing to log"
            )
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, (int, float)):
            raise ValueError(f"DiaryFood quantity must be a number, got {self.quantity!r}")
        if self.quantity < 0:
            raise ValueError(f"DiaryFood quantity cannot be negative, got {self.quantity}")


@dataclass(frozen=True)
class Entry:
    """One diary entry: its identity, its foods, and the provenance on it.

    ``id`` identifies the entry within the diary; ``created_at`` / ``updated_at``
    are the ISO-8601 timestamps of its first write and of its last edit; ``foods``
    is the list of foods consumed, each with its quantity; ``provenance`` is the
    closed-vocabulary value (``manual`` | ``imported``) stamped on the entry.
    """

    id: str
    created_at: str
    updated_at: str
    foods: tuple[DiaryFood, ...] = ()
    provenance: str = "manual"

    def __post_init__(self) -> None:
        if not str(self.id).strip():
            raise ValueError("Entry id is required: a diary entry with no id cannot be traced")
        for key in ("created_at", "updated_at"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Entry {key} is required — an ISO-8601 timestamp — got {value!r}"
                )
        object.__setattr__(self, "foods", tuple(self.foods))
        object.__setattr__(self, "provenance", validate_provenance(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entry to the plain mapping a store or snapshot persists."""
        return {
            "id": self.id,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "foods": [{"food": f.food, "quantity": f.quantity} for f in self.foods],
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Entry":
        """Inverse of :meth:`to_dict`, accepting either camelCase or snake_case keys."""

        def pick(*names: str, default: Any = None) -> Any:
            for name in names:
                if name in data:
                    return data[name]
            return default

        foods: tuple[DiaryFood, ...] = ()
        for item in pick("foods") or ():
            if isinstance(item, DiaryFood):
                foods = foods + (item,)
            elif isinstance(item, Mapping):
                foods = foods + (
                    DiaryFood(food=str(item["food"]), quantity=float(item["quantity"])),
                )
            else:
                raise ValueError(f"Entry foods must be DiaryFood or a mapping, got {item!r}")

        return cls(
            id=str(pick("id")),
            created_at=str(pick("createdAt", "created_at")),
            updated_at=str(pick("updatedAt", "updated_at")),
            foods=foods,
            provenance=str(pick("provenance", default="manual")),
        )


@dataclass(frozen=True)
class UndoSnapshot:
    """A device-local undo snapshot: the entry a just-logged write takes back.

    The snapshot envelope serialises the entry through the contract
    (:meth:`Entry.to_dict`) and carries its own schema version alongside the
    entry (:data:`SNAPSHOT_VERSION`). A reader validates the snapshot version
    before accepting the snapshot, so a snapshot minted by a different diary
    shape is refused rather than mistaken for one this build wrote.
    """

    entry: Entry

    def to_dict(self) -> dict[str, Any]:
        """Serialize the snapshot: the contract-serialised entry plus the version."""
        return {
            "version": SNAPSHOT_VERSION,
            "entry": self.entry.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UndoSnapshot":
        """Read a snapshot back, accepting only the current snapshot schema version."""
        version = data.get("version")
        if version != SNAPSHOT_VERSION:
            raise ValueError(
                f"Undo snapshot version {version!r} is not one this build can read; "
                f"expected {SNAPSHOT_VERSION!r}"
            )
        entry_data = data.get("entry")
        if not isinstance(entry_data, Mapping):
            raise ValueError("An undo snapshot requires an 'entry' mapping")
        return cls(entry=Entry.from_dict(entry_data))
