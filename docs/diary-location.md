# Diary location & contract findings — task `t_7d3debe1`

Scope of this note (facts only, task `t_7d3debe1` — *Locate diary/write-seam code and
the diary contract doc*): where diary entries are written (write seam / store) and where
the diary contract lives (README or docs). Recorded facts: entry schema, persistence/sync
path, export path, test setup.

## Where the diary code lives

The task workspace checkout — `/work/foodcore/ideas/37/repo`, branch
`forge/foodcore/t_da90581d`, HEAD `f34d831` (annotated tag `v0.2.4`) — is a **pre-diary**
foodcore checkout. File-tree inspection and `git ls-files` confirm it carries **no diary
module, no diary tests and no diary docs**. The diary subsystem exists only in the sibling
diary-bearing checkouts under `/work/foodcore/ideas/`:

| Checkout | Diary module | Module path | Diary tests |
|---|---|---|---|
| `/work/foodcore/ideas/16/repo` (branch `forge/foodcore/t_cd560d72`, HEAD `538a5b1`) | diary toast / inline edit sheet: undo, save, delete handlers, `LogEntry`, `LogToast`, `EditSheet` | `app/diary.py` → `foodcore.diary` | `tests/test_diary.py` (18 tests) |
| `/work/foodcore/ideas/9/repo` (branch `forge/foodcore/t_8ff0a241`, HEAD `05dbaaf`) | diary "Log again" row + "Logged" toast; diary store | `app/diary.py` → `foodcore.diary`; `app/store.py` → `foodcore.store` | `tests/test_diary.py` (14), `tests/test_store.py` |
| `/work/foodcore/ideas/7/repo` (branch `forge/foodcore/t_ec871437`, HEAD `5fa8b1f`) | diary SQLite store + CLI | `app/diary/` package → `foodcore.diary.db`; `app/cli.py` `diary` subcommands | `tests/test_diary.py` (11), `tests/test_roundtrip.py` (2), diary CLI cases in `tests/test_cli.py` |
| `/work/foodcore/ideas/8/repo` (branch `forge/foodcore/t_13c1e1cd`, HEAD `c9dd8e5`) | diary store + CSV importer | `app/store.py` → `foodcore.store`; `app/importer.py` → `foodcore.importer` | `tests/test_store.py` (11), `tests/test_import.py` (5) |

## The diary write seam

There is one write surface per diary-bearing checkout:

- **`foodcore.store`** (`app/store.py` in the `8` and `9` checkouts) — module docstring: "The
  diary store — the single write surface for food entries." The two rules that make the
  seam real: (1) **closed provenance vocabulary** — `source` is `manual` or `imported` and
  nothing else, defended by a SQL `CHECK` and re-checked in Python before any SQL runs; (2)
  **one writer path** — `add_entry` is the only function that writes, `add_imported` is a thin
  wrapper stamping `source="imported"`, and the module exports no connection helper, no cursor
  and no `exec` passthrough: callers pass in the connection from `init_db` and nothing else.
- Writes are **upserts** on the log slot — `PRIMARY KEY (user_id, date, meal, entry)` with
  `ON CONFLICT … DO UPDATE`, so re-logging replaces the prior row instead of duplicating it.
- The importer (`foodcore.importer.import_csv`) writes through `store.add_entry` with
  `source="imported"` and absorbs a primary-key collision as an idempotent no-op — never an
  overwrite.

- **`foodcore.diary.db`** (`app/diary/db.py` in the `7` checkout) — the store-as-package variant
  of the same seam: `init_db`, `add_entry(when, title, kind, note, kcal, tags, source, *, db) -> int`,
  `update_entry(entry_id, fields, *, db)`, `delete_entry(entry_id, *, db) -> bool`,
  `list_entries(*, db)`, `get_entry(entry_id, *, db)`, `import_csv(path, *, db) -> int`,
  `day_totals(*, db) -> dict[str, float]`. Default store file `data/diary.db`, created on first
  use; module-level lazy default connection plus per-call `db=` override.

- **Undo / edit-sheet handler layer** — `foodcore.diary` (`app/diary.py` in the `9` and `16`
  checkouts) owns the transient UI state: `LogEntry`, `UndoHandler` / `SaveHandler` / `DeleteHandler`,
  `undo_handler_for(entry, *, remove)`, `save_handler_for(*, save)`, `delete_handler_for(entry, *,
  remove)`, `LogToast` (`TOAST_WINDOW_SECONDS = 10`, `UNDO_LABEL`), `EditSheet`. The destructive
  step is **delegated** to a handler supplied by the host component that owns the entries, so the
  diary module never writes to the store itself.

## Where the diary contract lives

**No diary contract document exists yet.** The only diary-adjacent docs found under `/work`:

- `/work/foodcore/ideas/31/repo/docs/diary-location.md` — task `t_c2e46e68` "Locate diary code and
  test gate" findings.
- `/work/foodcore/ideas/9/repo/docs/notes/t_2dbdc7ce-locate-repo-facts.md` — task `t_2dbdc7ce`
  "Locate foodcore repo, stack, data model and home/day-view code" survey.

The `README.md` of every foodcore checkout documents the reference-data contract
(`Provenance` / `Resolved` / `Unresolved` / `Outcome` / vocabularies / dataset versioning) and
carries **no diary content**. There is therefore no diary contract file to extend today — the
stub-section condition of this task ("commit only if the contract file needs a stub section") is
not met, and the facts-recording task folds into the follow-up that writes the diary contract.

## Recorded facts

### Entry schema

Two coexisting diary entry shapes:

1. **`foodcore.store` shape** (`entries` table; log slot = one row per
   `(user_id, date, meal, entry)`):
   `user_id`, `date`, `meal`, `entry`, `kcal REAL NOT NULL`, `note`, `source TEXT NOT NULL CHECK
   (source IN ('manual','imported'))`, `created_at TEXT NOT NULL`; `PRIMARY KEY (user_id, date, meal, entry)`.
   Re-log → upsert replaces kcal/note/source/created_at on the same slot.

2. **`foodcore.diary.db` shape** (`entries` table; surrogate key `id INTEGER PRIMARY KEY` plus
   `when`, `kind`, `title`, `note`, `kcal`, `tags`, `source`):
   `kind` CHECK (`meal` | `food`), `source` CHECK (`manual` | `imported`) NOT NULL DEFAULT
   `manual`, `kcal REAL` nullable (an unmeasured eating occasion stays `NULL`, not guessed).

### Persistence / sync path

Device-local SQLite only; **no sync layer exists yet**. Undo is therefore device-local and must
stay ephemeral (in-memory, windowed, dropped on undo; tombstone rather than restore if cross-device
sync ever exists).

### Export path

**None found.** No diary export function exists in any checkout; the only "export" hits in the
diary-adjacent code are the USDA FoodData Central dataset exports.

### Test setup

**pytest, not npm.** `python3 -m pytest -q` from the checkout; `[tool.pytest.ini_options]
testpaths = ["tests"]`; dev extra `pytest>=8.0` + `ruff>=0.16`; CI (`.github/workflows/ci.yml`) =
`ruff check .` + `python -m pytest -q` on a Python 3.10/3.12 matrix plus a clean-venv install
acceptance job.

## Finding

The diary write seam is a deliberate single-writer design (`foodcore.store.add_entry` being the
only write; provenance CHECK + Python re-check; upsert on the log slot), the undo/edit-sheet layer
is handler-delegated so the diary module never writes, and the diary contract document does not
exist yet — the next task in the chain writes it.
