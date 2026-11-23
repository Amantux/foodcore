# foodcore — location & stack facts

Task: `t_2dbdc7ce` — *Locate foodcore repo, stack, data model and home/day-view code*
Worker: `p-foodcore-implement-omlx-18`
Date: 2026-11-22

## Repository

- Repo: **foodcore** — shared food reference logic for **myMeal** and **Edibl**.
- Path: `/work/foodcore/ideas/9/repo`
- Branch: `forge/foodcore/t_8ff0a241` — HEAD `f34d83155b72e4d5610d2321d0b9702a8e7df57e`
  (annotated tag: `v0.2.4`), working tree clean, **no remote configured** (do not push).
  Do not switch or rename the branch.
- Sibling clones holding other idea branches of the same repo:
  - `/work/foodcore/ideas/7/repo` — `forge/foodcore/t_ec871437` @ `f34d831` (v0.2.4)
  - `/work/foodcore/ideas/8/repo` — `forge/foodcore/t_13c1e1cd` @ `87712f4` (diary store + CSV importer)
  - `/work/foodcore/ideas/16/repo` — `forge/foodcore/t_cd560d72` @ `f78351b` (diary post-log toast)

The diary subsystem (`app/store.py`, `app/importer.py`, `app/diary.py` and their
tests) exists only in the `8` and `16` checkouts; this task's workspace checkout
(`9`) predates it.

## Stack

- Language: Python `>=3.10` (package floor; CI matrix runs 3.10 and 3.12; local
  interpreter 3.12.13).
- Framework: **none** — it is a library, not a service (no container, no DB server, no
  HTTP port, no Home Assistant add-on).
- DB / ORM: **none**. Zero runtime dependencies is a hard rule (`pyproject.toml`).
  Standard library only: `sqlite3` (reference dataset file), `csv` (importer),
  `json`. No SQLAlchemy/Flask/alembic. Host-owned persistence: `SourceRecord` is a
  plain frozen dataclass, "Persistence is yours".
- Test runner: **pytest** (`dev` extra: `pytest>=8.0`, `ruff>=0.16`).

## Test command (native runner, recorded)

- `python -m pytest -q` — works from the checkout, no install needed.
- Lint: `ruff check .`
- CI: `.github/workflows/ci.yml` — `ruff check .` + `python -m pytest -q` on the
  3.10/3.12 matrix, plus a clean-venv install / zero-runtime-dependency /
  installed-artifact acceptance job.

Result at survey time: **`python -m pytest -q` → 561 passed**.

## Data model / entry model

- Reference data: `Dataset`, `FoodRecord`, `FoodRow`, `Portion`, `FoodMatch`;
  portions keyed on `(food_key, measure, size, qualifier, amount, source_id)`;
  `DATASET_SCHEMA_VERSION = 3`, `RULE_EPOCH = 1`.
- Diary entries — as found in the diary-bearing checkouts:
  `entries` table with `PRIMARY KEY (date, meal)`,
  `kcal REAL NOT NULL, note TEXT, source TEXT NOT NULL
   CHECK (source IN ('manual','imported')), created_at TEXT NOT NULL`.
- Single write surface: `foodcore.store.init_db` / `add_entry` / `add_imported`;
  `foodcore.importer.import_csv` reads the diary CSV (header `date,meal,kcal,note`)
  and writes through the store with `source="imported"`. A re-import colliding on the
  `(date, meal)` primary key is treated as an idempotent no-op — never an overwrite.
- The planned diary key — upsert on `(day, meal-time, entry)` with per-user last-used
  tracking and a quantity — **does not exist in any checkout yet**; the current diary
  key is `(date, meal)`, entries carry kcal only, and there is no user column.

## Home / day-view / add-edit flow

- **Not present in this repository or workspace.** `foodcore` is a library consumed
  in-process by the host apps; the home screen, day view, add/edit sheet, the
  "Log again" row and the "Logged" confirmation are host-app UI surfaces. No such
  code was found anywhere under `/work` or `/opt/data` in this environment.
- Library-side surfaces relevant to that flow: `foodcore.datasets.Dataset` (food and
  entry lookups), `foodcore.store` (writes), `foodcore.importer` (writes),
  `foodcore.diary.LogToast` (post-log transient undo), and the engines
  `foodcore.convert`, `foodcore.nutrition`, `foodcore.allergens`, `foodcore.dietary`.

## Recorded answers for task t_2dbdc7ce

- Repo path: `/work/foodcore/ideas/9/repo`
- Stack: Python ≥3.10, zero runtime deps (stdlib `sqlite3`/`csv`/`json`), no framework,
  no ORM; pytest + ruff.
- Test command: `python -m pytest -q` (561 passed).
- Home screen file: **n/a in this repo** (host apps own it).
- Entry storage file: `app/store.py` + `entries` table (`app/store`, diary checkouts).
- Existing upsert/write pattern: plain `INSERT` via the single writer path; importer
  absorbs primary-key collision as idempotent no-op (not an upsert).
- Screens involved: home screen, day view, add/edit sheet (host apps); diary
  store / importer / toast (library).
