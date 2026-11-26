"""The diary write seam — the upsert path goes through the contract."""
from pathlib import Path

import pytest

from foodcore.diary import Entry, EntryStore, PROVENANCE_VOCABULARY
from foodcore.provenance import VocabularyError


#: The minimal sample entry the upsert path is checked against.
SAMPLE = {
    "id": "e-2026-01-01-0001",
    "createdAt": "2026-01-01T09:00:00",
    "updatedAt": "2026-01-01T09:00:00",
    "foods": [{"food": "eggs", "quantity": 2}],
    "provenance": "manual",
}


def test_the_store_reads_the_contract_vocabulary() -> None:
    assert EntryStore().provenance_vocabulary == PROVENANCE_VOCABULARY
    assert frozenset({"manual", "imported"}) == PROVENANCE_VOCABULARY


def test_upsert_builds_the_entry_through_the_contract() -> None:
    entry = EntryStore().upsert(SAMPLE)

    assert entry.id == "e-2026-01-01-0001"
    assert entry.created_at == "2026-01-01T09:00:00"
    assert entry.updated_at == "2026-01-01T09:00:00"
    assert entry.provenance == "manual"
    assert len(entry.foods) == 1
    assert entry.foods[0].food == "eggs"
    assert entry.foods[0].quantity == 2


def test_upsert_refuses_an_entry_outside_the_contract_vocabulary() -> None:
    store = EntryStore()

    with pytest.raises(VocabularyError):
        store.upsert({**SAMPLE, "provenance": "guessed"})


def test_a_fresh_store_reads_back_an_entry_written_by_a_previous_store(tmp_path: Path) -> None:
    """The store is durable: a fresh instance opened on the same backing file
    reads back what the previous instance wrote, through the contract schema."""
    first = EntryStore(tmp_path / "diary.sqlite")
    entry = first.upsert(SAMPLE)

    second = EntryStore(tmp_path / "diary.sqlite")
    stored = second.get(entry.id)

    assert stored is not None
    assert stored == entry
    assert stored.to_dict() == entry.to_dict()
    assert Entry.from_dict(stored.to_dict()) == stored
