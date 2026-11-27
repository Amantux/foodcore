# Diary store audit — task `t_8f013b97`

Date: 2026-11-26 · Audit task in the foodcore diary full-delete / purge chain.

Scope: find every store the diary touches — the entries database, the undo/redo
snapshots (idea 37), the edit/undo logs, the caches, the temp/pending export files
— and the existing full-delete code path (idea 48) — and record the inventory
(file paths, tables, file locations, invariants).

## 1. Verdict for this checkout

`/work/foodcore/ideas/50/repo` (branch `forge/foodcore/t_95514586`, HEAD
`f34d831`, annotated tag `v0.2.4`) is a **pre-diary** checkout.

Verified on purpose:

- `git ls-files` lists no diary, snapshot, purge, undo or export-delete paths.
- Case-insensitive `grep -ril diary` over the working tree (excluding `.git`)
  returns **no hits** — not in `app/`, not in `tests/`, not in any doc, not in
  `README.md`.
- `app/` contains only the reference-data library (`allergens`, `cli`, `convert`,
  `datasets`, `dietary`, `nutrition`, `provenance`, `registry`, `units`) plus
  `app/data/`, `app/rules/`, `app/sources/`.

**Conclusion: the diary does not exist yet in this checkout.** There is no
entries database, no undo/redo snapshot store, no edit/undo log, no cache, no
temp/pending export file and no full-delete path here yet. The full-delete work
of idea 48 and the undo contract of idea 37 live in the sibling diary-bearing
checkouts under `/work/foodcore/ideas/`; the inventory below is what the audit
found there, and §3 defines the intended store layout this checkout will build
toward.

## 2. Inventory of the diary stores (found in the diary-bearing checkouts)

### 2.1 Entries database

| Checkout | Module | Diary module | Entries table |
|---|---|---|---|
| `/work/foodcore/ideas/7/repo` (t_ec871437) | `app/diary/db.py` | `foodcore.diary.db` (`init_db`, `add_entry`, `update_entry`, `delete_entry`, `list_entries`, `get_entry`, `import_csv`, `day_totals`) | `entries(id INTEGER PK, when, kind CHECK (meal\|food), title, note, kcal REAL NULLABLE, tags, source CHECK (manual\|imported))`; default store file `data/diary.db` |
| `/work/foodcore/ideas/8/repo`, `/work/foodcore/ideas/9/repo` | `app/store.py` | `foodcore.store` (single write surface: `add_entry`, `add_imported`) | `entries` PK `(user_id, date, meal, entry)`, `source CHECK (manual\|imported)`, `kcal REAL NOT NULL`; re-log is an upsert that replaces the slot |
| `/work/foodcore/ideas/38/repo`, `/work/foodcore/ideas/46/repo`, `/work/foodcore/ideas/48/repo` | `app/diary/store.py` | `foodcore.diary.store` (`DiaryStore`) | `meta(key TEXT PK, value TEXT NOT NULL)` + `entries(entry_id TEXT PK, day, food, portion, slot, notes, provenance CHECK (provenance IN ('manual','import')), created_at, updated_at, schema_version TEXT NOT NULL)`; default store file `DEFAULT_DIARY_DB = "~/.foodcore/diary.db"` |

### 2.2 Undo/redo snapshots (idea 37)

- Contract doc: `/work/foodcore/ideas/37/repo/docs/diary-contract.md`.
- One-line contract: **"the synced store only ever receives final entries with
  valid provenance; snapshots never cross."**
- Undo window: `TOAST_WINDOW_SECONDS = 10`; window inclusive at boundary;
  expired/absent undo leaves the entry as written.
- `UndoSnapshot` (ideas/38, 46) serialises the entry via the contract plus its own
  envelope version: `to_dict() -> {"version": SNAPSHOT_VERSION, "entry": ...}`,
  `from_dict()` refuses any version other than `SNAPSHOT_VERSION` (`"1"`).
- Ephemeral rule: snapshot is process-local, never persisted, never serialised,
  never handed to the store / export payload / model; pruned after window, dropped
  on undo.
- Tombstone-vs-restore: undo deletes the current row via the delegated handler —
  never writes the prior entry back into a shared location.

### 2.3 Edit/undo logs

- No persistent edit/undo log table exists in the diary-bearing code found.
- Undo is an ephemeral snapshot + delegated row removal; delete-side enumeration
  uses derived-table names instead of a dedicated log table.

### 2.4 Caches

- Derived purge target: `last_used` (per-user last-used tracking / top-5 query).

### 2.5 Temp/pending export files

- Export path: `export_diary(store, dest_path)` in
  `/work/foodcore/ideas/48/repo/app/diary/export.py` — read-only view over the
  store, user-chosen destination, no default path, writes
  `{"schemaVersion": N, "entries": [...]}` JSON; entry keys closed
  (`entryId, day, food, portion, slot, notes, provenance, createdAt, updatedAt,
  schemaVersion`); refuses host-account / third-party-bound identifiers.
- No temp/pending export directory observed.

### 2.6 Full-delete code path (idea 48)

- `/work/foodcore/ideas/48/repo/app/diary/delete.py` → `delete_all(store, confirm=None) -> int`.
- Confirmation gate: typed `True` or a non-blank token; anything else raises
  `DiaryDeleteError` and leaves the store untouched.
- Purge: `store.delete_entries()` (purges `entries`, returns purged count) then
  `store.purge_derived_table(t)` for each table in
  `DIARY_DELETE_TABLES = ("undo_snapshots", "favorites", "last_used")` (absent
  table ⇒ no-op, not a creation).
- Audit line: exactly one, via `logging.getLogger("foodcore.diary")`:
  `diary deleted: entries={count} at {timestamp}` — fact only (count + timestamp);
  never content, entry ids or filenames.

### 2.7 Invariants observed across the diary surface

- One-line write contract; single write seam (log / edit / undo / re-log / import
  all through one path; provenance stamped in one place; snapshots never cross).
- Fail-closed: future diary schema refused; unknown entry fields rejected; closed
  provenance vocabulary.
- Privacy boundary: `redact()` allowlist
  (`entryId, day, provenance, schemaVersion`); delete audit line is fact-only.
- Delete requires explicit confirmation; delete is fail-closed.
- Undo ephemeral / windowed / tombstone-not-restore; undo never touches store,
  export or model.
- Export is read-only over the store, user-chosen dest, closed shape.

## 3. Intended store layout (for the diary to be built in this checkout)

Because the diary does not exist in `/work/foodcore/ideas/50/repo`, the intended
layout the follow-up cards build toward:

- **entries DB** — SQLite file (device-local; default `DEFAULT_DIARY_DB =
  "~/.foodcore/diary.db"` in the subpackage form, `data/diary.db` in the db-package
  form), tables: `meta` (key/value, holds `schema_version`) + `entries` (final,
  user-written facts), plus derived tables added later.
- **snapshots** — undo/redo: per idea 37 currently an ephemeral in-memory
  `UndoSnapshot` (never persisted); the delete sweep already enumerates the
  derived table `undo_snapshots`.
- **logs** — edit/undo logs: no persistent log table found yet; undo is the
  ephemeral snapshot + delegated removal.
- **cache** — `last_used` derived table (per-user last-used / top-5).
- **pending export dir** — user-chosen export destination (no default); no
  temp/pending export directory observed yet.

## 4. Verification

Run in `/work/foodcore/ideas/50/repo`:

- `python3 -m pytest -q` → **561 passed** (baseline green; no diary tests exist
  here, so this is the pre-diary baseline).
- `grep -ril diary . --exclude-dir=.git` → **no hits** (diary absent).
- `grep -rin "delete\|export\|snapshot"` → only reference-data / USDA
  export + dataset-snapshot hits; **no diary code hits**.

## 5. Handoff summary for the implementer

1. Audit complete: the diary stores the delete/export/purge chain must be built
   from scratch in this checkout (§2 inventories the shapes already prototyped in
   the sibling checkouts, §3 the intended layout).
2. Plan note committed at `docs/diary-store-audit.md`.
3. Follow-up cards (from the parent plan) consume this inventory: purge sweep +
   receipt, fail-closed full-delete wiring, tombstoned/empty export, end-to-end
   tests.
