"""The diary entry contract — the single versioned schema for diary entries.

The check for this contract is deliberately small: the module must expose the
Entry schema, the closed provenance vocabulary and the contract version, the
schema must accept a minimal sample entry and refuse one outside the vocabulary,
and every writer and reader must round-trip that entry through the same schema.
"""
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import foodcore
import foodcore.diary.contract as diary_contract
from foodcore.diary import (
    CONTRACT_VERSION,
    SNAPSHOT_VERSION,
    DiaryFood,
    Entry,
    EntryStore,
    PROVENANCE_VOCABULARY,
    UndoSnapshot,
)
from foodcore.diary.contract import validate_provenance
from foodcore.provenance import VocabularyError


#: The minimal sample entry a valid diary entry is checked against.
MINIMAL_SAMPLE = {
    "id": "e-2026-01-01-0001",
    "created_at": "2026-01-01T09:00:00",
    "updated_at": "2026-01-01T09:00:00",
    "foods": [{"food": "eggs", "quantity": 2}],
    "provenance": "manual",
}

#: The sample entry every writer and reader is round-tripped against — the same
#: shape the contract serialises, in the persisted (camelCase) spelling.
ROUND_TRIP_SAMPLE = {
    "id": "e-2026-01-01-0001",
    "createdAt": "2026-01-01T09:00:00",
    "updatedAt": "2026-01-01T09:00:00",
    "foods": [{"food": "eggs", "quantity": 2}],
    "provenance": "manual",
}


def _entry(**overrides) -> Entry:
    fields = dict(MINIMAL_SAMPLE)
    fields.update(overrides)
    provenance = fields["provenance"] if fields.get("provenance") is not None else "manual"
    return Entry(
        id=fields["id"],
        created_at=fields["created_at"],
        updated_at=fields["updated_at"],
        foods=tuple(
            DiaryFood(food=f["food"], quantity=f["quantity"]) for f in fields.get("foods") or ()
        ),
        provenance=provenance,
    )


# --- the module exposes the contract ----------------------------------------


def test_the_contract_module_exposes_entry_vocabulary_and_version():
    assert diary_contract.Entry is Entry
    assert diary_contract.PROVENANCE_VOCABULARY == frozenset({"manual", "imported"})
    assert diary_contract.CONTRACT_VERSION == "1"
    assert CONTRACT_VERSION == "1"


def test_the_contract_version_is_the_initial_shape_version():
    assert isinstance(CONTRACT_VERSION, str)
    assert CONTRACT_VERSION == "1"


def test_the_snapshot_version_is_the_initial_snapshot_version() -> None:
    assert isinstance(SNAPSHOT_VERSION, str)
    assert SNAPSHOT_VERSION == "1"


def test_the_provenance_vocabulary_is_the_closed_set() -> None:
    assert PROVENANCE_VOCABULARY == frozenset({"manual", "imported"})


# --- the schema validates a minimal sample entry ----------------------------


def test_a_minimal_sample_entry_is_accepted():
    entry = _entry()

    assert entry.id == "e-2026-01-01-0001"
    assert entry.created_at == "2026-01-01T09:00:00"
    assert entry.updated_at == "2026-01-01T09:00:00"
    assert entry.provenance == "manual"
    assert len(entry.foods) == 1
    assert entry.foods[0].food == "eggs"
    assert entry.foods[0].quantity == 2


def test_an_entry_without_foods_is_valid():
    assert _entry(foods=[]).foods == ()


def test_a_missing_id_is_refused():
    with pytest.raises(ValueError):
        Entry(
            id="  ",
            created_at="2026-01-01T09:00:00",
            updated_at="2026-01-01T09:00:00",
        )


def test_missing_timestamps_are_refused():
    with pytest.raises(ValueError):
        Entry(id="e1", created_at="", updated_at="2026-01-01T09:00:00")
    with pytest.raises(ValueError):
        Entry(id="e1", created_at="2026-01-01T09:00:00", updated_at="   ")


# --- the schema refuses an unknown provenance value ------------------------


@pytest.mark.parametrize(
    "bad",
    ["", "Manual", "IMPORTED", "manual ", "guessed", "derived", 3, "planned"],
)
def test_an_unknown_provenance_is_refused(bad):
    with pytest.raises(VocabularyError):
        _entry(provenance=bad)


def test_an_unknown_provenance_error_names_the_accepted_values():
    with pytest.raises(VocabularyError) as exc:
        _entry(provenance="guessed")

    message = str(exc.value)
    assert "guessed" in message
    assert "manual" in message
    assert "imported" in message


def test_a_known_provenance_is_accepted() -> None:
    assert _entry(provenance="manual").provenance == "manual"
    assert _entry(provenance="imported").provenance == "imported"


# --- the provenance CHECK itself --------------------------------------------


def test_the_provenance_check_accepts_the_contract_vocabulary() -> None:
    # The CHECK reads the same vocabulary the contract declares, so the two can
    # never drift apart: whatever PROVENANCE_VOCABULARY holds is what the CHECK
    # accepts.
    assert set(PROVENANCE_VOCABULARY) == {"manual", "imported"}
    assert validate_provenance("manual") == "manual"
    assert validate_provenance("imported") == "imported"


@pytest.mark.parametrize(
    "bad",
    ["", "Manual", "IMPORTED", "manual ", "guessed", "derived", 3, "planned"],
)
def test_the_provenance_check_rejects_a_value_outside_the_vocabulary(bad) -> None:
    with pytest.raises(VocabularyError):
        validate_provenance(bad)


def test_the_provenance_check_error_names_the_accepted_values() -> None:
    with pytest.raises(VocabularyError) as exc:
        validate_provenance("guessed")

    message = str(exc.value)
    assert "guessed" in message
    assert "manual" in message
    assert "imported" in message


# --- the foods on an entry are themselves validated ------------------------


def test_a_diary_food_requires_a_name_and_a_quantity():
    with pytest.raises(ValueError):
        DiaryFood(food="  ", quantity=2)
    with pytest.raises(ValueError):
        DiaryFood(food="eggs", quantity=-1)
    with pytest.raises(ValueError):
        DiaryFood(food="eggs", quantity="two")


def test_a_diary_food_accepts_a_zero_quantity():
    assert DiaryFood(food="eggs", quantity=0).quantity == 0


# --- serialization round-trips through the same schema ----------------------


def test_the_entry_round_trips_through_its_serializer():
    entry = _entry()

    restored = Entry.from_dict(entry.to_dict())

    assert restored == entry
    assert restored.to_dict() == entry.to_dict()


def test_the_entry_serializer_accepts_snake_case_keys():
    restored = Entry.from_dict({
        "id": "e-2026-01-01-0001",
        "created_at": "2026-01-01T09:00:00",
        "updated_at": "2026-01-01T09:00:00",
        "foods": [{"food": "eggs", "quantity": 2}],
        "provenance": "manual",
    })

    assert restored.id == "e-2026-01-01-0001"
    assert restored.foods[0].food == "eggs"
    assert restored.provenance == "manual"


def test_the_entry_is_frozen() -> None:
    entry = _entry()

    with pytest.raises(FrozenInstanceError):
        entry.id = "changed"


# --- the contract round-trips a sample entry through every writer and reader --


def test_the_upsert_writer_round_trips_a_sample_entry_through_the_contract() -> None:
    """The write seam is a writer and a reader: the entry it stores comes back
    through the contract's own serializer, unchanged."""
    store = EntryStore()
    entry = store.upsert(ROUND_TRIP_SAMPLE)
    stored = store.get(entry.id)
    assert stored is not None

    # The stored entry is read back through the same contract serializer, so
    # the upsert path round-trips a sample entry exactly as the contract defines.
    assert Entry.from_dict(stored.to_dict()) == stored
    assert stored.to_dict() == entry.to_dict()


def test_the_check_validated_write_round_trips_a_sample_entry_through_the_contract() -> None:
    """The storage CHECK and the contract serializer are the same gate: a sample
    entry written through the contract serialises to itself and still passes the
    CHECK when read back."""
    entry = Entry.from_dict(ROUND_TRIP_SAMPLE)

    assert validate_provenance(entry.provenance) == entry.provenance
    restored = Entry.from_dict(entry.to_dict())
    assert validate_provenance(restored.provenance) == restored.provenance
    assert restored == entry
    assert restored.to_dict() == entry.to_dict()


# --- the entry shape is owned by the contract alone ----------------------------


#: The persisted entry-shape key spellings. They appear only in the contract
#: module, which is the single writer and reader of the shape; anywhere else they
#: must not appear, or a module is hand-building entry dicts that drift from it.
ENTRY_KEY_MARKERS = ("createdAt", "created_at", "updatedAt", "updated_at")


def _diary_source_files() -> list[Path]:
    diary_dir = Path(foodcore.__file__).parent / "diary"
    return sorted(
        path
        for path in diary_dir.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )


def test_no_module_outside_the_contract_builds_an_entry_dict_by_hand() -> None:
    """Grep the diary sources: nothing but the contract may hand-write the entry
    shape, so no module can build an Entry dict by hand and drift from it."""
    contract_path = (Path(foodcore.__file__).parent / "diary" / "contract.py").resolve()

    hand_built = [
        str(path)
        for path in _diary_source_files()
        if path.resolve() != contract_path
        and any(marker in path.read_text(encoding="utf-8") for marker in ENTRY_KEY_MARKERS)
    ]

    assert hand_built == []


# --- the undo snapshot envelope serialises through the contract ------------------


def test_the_undo_snapshot_round_trips_a_sample_entry_through_the_contract() -> None:
    snapshot = UndoSnapshot(entry=_entry())

    restored = UndoSnapshot.from_dict(snapshot.to_dict())

    assert restored == snapshot
    assert restored.entry == snapshot.entry
    assert restored.entry.to_dict() == snapshot.entry.to_dict()


def test_the_undo_snapshot_serialises_the_entry_and_carries_the_snapshot_version() -> None:
    snapshot = UndoSnapshot(entry=_entry())
    payload = snapshot.to_dict()

    assert payload["version"] == SNAPSHOT_VERSION
    assert payload["entry"] == snapshot.entry.to_dict()


def test_the_undo_snapshot_round_trips_foods_through_the_contract_serializer() -> None:
    snapshot = UndoSnapshot(entry=_entry(foods=[{"food": "eggs", "quantity": 2}]))

    restored = UndoSnapshot.from_dict(snapshot.to_dict())

    assert len(restored.entry.foods) == 1
    assert restored.entry.foods[0].food == "eggs"
    assert restored.entry.foods[0].quantity == 2


@pytest.mark.parametrize("version", ["2", "0", "manual", "", None, 1])
def test_the_undo_snapshot_refuses_a_snapshot_with_an_unknown_schema_version(version) -> None:
    payload = UndoSnapshot(entry=_entry()).to_dict()
    payload["version"] = version

    with pytest.raises(ValueError):
        UndoSnapshot.from_dict(payload)


def test_the_undo_snapshot_refuses_a_snapshot_without_a_schema_version() -> None:
    payload = UndoSnapshot(entry=_entry()).to_dict()
    del payload["version"]

    with pytest.raises(ValueError):
        UndoSnapshot.from_dict(payload)


def test_the_undo_snapshot_refuses_an_entry_outside_the_contract() -> None:
    payload = UndoSnapshot(entry=_entry()).to_dict()
    payload["entry"]["provenance"] = "guessed"

    with pytest.raises(VocabularyError):
        UndoSnapshot.from_dict(payload)
