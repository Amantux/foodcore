"""The diary write seam — the only way an entry is created or updated.

The rejection tests assert the raise explicitly, so each one would pass
vacuously if the guard were removed; they check the error type, not just that
failure happens.
"""
import pytest

from foodcore.diary import (
    DiaryEntry,
    DiaryProvenanceError,
    EntryStore,
)


def _entry(eid: str, text: str) -> DiaryEntry:
    return DiaryEntry(id=eid, text=text, provenance="manual")


# --- provenance: the diary's closed CHECK enum ---------------------------

@pytest.mark.parametrize("ok", ["manual", "imported"])
def test_provenance_within_the_check_enum_is_accepted(ok):
    store = EntryStore()
    entry = DiaryEntry(id="d1", text="ate the rice", provenance=ok)
    store.upsert(entry, ok, origin="synced")
    assert store.get("d1") is not None
    assert store.get("d1").provenance == ok


@pytest.mark.parametrize(
    "bad",
    ["", "Manual", "IMPORTED", "manual ", "guessed", "derived", None, 3],
)
def test_provenance_outside_the_check_enum_is_refused(bad):
    store = EntryStore()
    with pytest.raises(ValueError):
        store.upsert(_entry("d1", "note"), bad, origin="synced")


def test_provenance_error_names_the_accepted_values():
    with pytest.raises(DiaryProvenanceError) as exc:
        EntryStore().upsert(_entry("d1", "note"), "guessed", origin="synced")
    message = str(exc.value)
    assert "guessed" in message
    for ok in ("manual", "imported"):
        assert ok in message


# --- the synced store only ever receives final entries -------------------

def test_synced_store_row_is_written_with_the_provenance_stamped():
    store = EntryStore()
    store.upsert(_entry("d1", "ate the rice"), "manual", origin="synced")
    assert store.get("d1") == DiaryEntry(
        id="d1", text="ate the rice", provenance="manual"
    )


def test_device_local_write_writes_a_snapshot_and_not_the_synced_store():
    store = EntryStore()
    store.upsert(_entry("d1", "ate the rice"), "manual", origin="device-local")
    assert store.snapshot("d1") is not None  # undo snapshot written...
    assert store.get("d1") is None  # ...and never entered the synced store.


def test_synced_write_purges_the_stale_device_local_snapshot():
    store = EntryStore()
    store.upsert(
        DiaryEntry(id="d1", text="ate the rice", provenance="imported"),
        "imported",
        origin="device-local",
    )
    store.upsert(
        DiaryEntry(id="d1", text="ate the rice", provenance="imported"),
        "imported",
        origin="synced",
    )
    assert store.get("d1") is not None
    assert store.snapshot("d1") is None  # a final entry supersedes the snapshot.


# --- undo / re-log preserve the original provenance ----------------------

def test_relog_preserves_the_original_provenance():
    store = EntryStore()
    store.upsert(
        DiaryEntry(id="d1", text="ate the rice", provenance="imported"),
        "imported",
        origin="device-local",
    )
    snap = store.snapshot("d1")
    assert snap is not None
    assert snap.provenance == "imported"

    # Undo + re-log: the re-logged entry re-carries the ORIGINAL provenance
    # through the seam, never a default to manual.
    store.upsert(
        DiaryEntry(id="d1", text="ate the rice", provenance=snap.provenance),
        snap.provenance,
        origin="synced",
    )
    assert store.get("d1").provenance == "imported"


def test_origin_outside_the_known_set_is_refused():
    with pytest.raises(ValueError):
        EntryStore().upsert(_entry("d1", "note"), "manual", origin="who-knows")


# --- the entry's carried provenance is authoritative ------------------------

def test_caller_arg_provenance_disagreeing_with_the_entry_is_refused():
    store = EntryStore()
    entry = DiaryEntry(id="d1", text="ate the rice", provenance="imported")
    with pytest.raises(DiaryProvenanceError):
        store.upsert(entry, "manual", origin="synced")
    with pytest.raises(DiaryProvenanceError):
        store.upsert(entry, "manual", origin="device-local")


def test_relog_of_an_imported_entry_keeps_imported_provenance():
    store = EntryStore()
    entry = DiaryEntry(id="d1", text="ate the rice", provenance="imported")

    # Device-local write / re-save keeps the imported provenance in the snapshot.
    store.upsert(entry, "imported", origin="device-local")
    store.upsert(entry, "imported", origin="device-local")
    assert store.snapshot("d1") is not None
    assert store.snapshot("d1").provenance == "imported"

    # Synced re-log keeps the imported provenance and never flips to manual.
    store.upsert(entry, "imported", origin="synced")
    assert store.get("d1") is not None
    assert store.get("d1") == DiaryEntry(
        id="d1", text="ate the rice", provenance="imported"
    )


def test_overwrite_of_a_synced_entry_with_a_different_provenance_is_refused():
    store = EntryStore()
    store.upsert(
        DiaryEntry(id="d1", text="ate the rice", provenance="imported"),
        "imported",
        origin="synced",
    )
    with pytest.raises(DiaryProvenanceError):
        store.upsert(
            DiaryEntry(id="d1", text="ate the rice", provenance="manual"),
            "manual",
            origin="synced",
        )
    # The refused write left the final entry untouched.
    assert store.get("d1") == DiaryEntry(
        id="d1", text="ate the rice", provenance="imported"
    )


def test_valid_same_provenance_upsert_still_passes():
    store = EntryStore()
    store.upsert(
        DiaryEntry(id="d1", text="ate the rice", provenance="imported"),
        "imported",
        origin="synced",
    )
    store.upsert(
        DiaryEntry(id="d1", text="cooked the rice", provenance="imported"),
        "imported",
        origin="synced",
    )
    assert store.get("d1") is not None
    assert store.get("d1").text == "cooked the rice"
    assert store.get("d1").provenance == "imported"
