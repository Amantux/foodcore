# Diary contract

Scope of this document: the diary's contract — the one-line invariant the write
seam enforces, and the **undo** semantics the diary is written against.

Facts recorded by task `t_7d3debe1` (*Locate diary/write-seam code and the diary
contract doc*) about the entry schema, the write seam, the persistence path and
the export path live in [diary-location.md](diary-location.md). This file is the
contract those facts feed.

## The one-line contract

> The synced store only ever receives final entries with valid provenance; snapshots never cross.

Every diary write — log, edit, undo, re-log, import — goes through the single write
path (`EntryStore.upsert` / the store's `add_entry`), so provenance is stamped in
exactly one place and a provisional undo snapshot can never be mistaken for final
state.

## Undo semantics

### The undo window (10 seconds)

The post-log confirmation (`LogToast`) carries the Undo control and is time-boxed:
`TOAST_WINDOW_SECONDS = 10`, so a confirmation minted at `now` expires at
`now + 10s`. The window is inclusive at its boundary — an undo arriving at exactly
`now == expires_at` is already expired — and an undo that is expired, or that has no
handler, leaves the just-logged entry exactly as it was written.

An undo therefore takes the just-logged entry back only when it lands inside the
window.

### The device-local / ephemeral snapshot rule

Each successful log mints a fresh in-memory snapshot of the prior entry that the
undo may take back (`UndoSnapshot`, holding a plain in-memory `LogEntry` plus the
snapshot's `expires_at`). The snapshot is process-local and ephemeral: it is never
persisted, never serialised and never handed to the store, the export payload or the
model. It is pruned once the undo window elapses, and an undo drops it immediately.

### The tombstone-vs-restore rule

Undo takes the just-logged entry back by deleting the current row, through the
handler the host component supplies — it never writes the prior entry back into any
shared location. The prior entry therefore never leaves the process, and an undo is
a device-local tombstone rather than a restore. Should cross-device sync ever exist,
undo must remain a tombstone rather than a restore.

### Undo never touches sync, export or model

The undo path reasons only over plain in-memory diary entries; anything else — a
store row, an export payload, a model call result — is refused. The undo reaches the
diary only through the delegated removal of the just-logged entry: it never writes to
the synced store, never builds an export payload and never calls the model, and never
serialises the snapshot.

## What undo is not

Only the last logged entry is ever undoable — no history is kept, so an undo can only
ever take back the entry it was minted for. An undo whose just-logged entry is already
gone has nothing left to take back and is a no-op, and a delete followed by a save
edits one entry: the edited payload, not a resurrected duplicate.
