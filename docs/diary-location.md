# Diary location findings — task `t_c2e46e68`

## Where the diary code and tests actually live

The assigned workspace checkout — `/work/foodcore/ideas/31/repo`, branch
`forge/foodcore/t_ee1d617d`, HEAD `f34d831` (annotated tag `v0.2.4`) — is a clean
tree at the **pre-diary** base commit and carries **no diary module and no diary
test file**.

The diary subsystem exists only in the sibling diary-bearing checkouts under
`/work/foodcore/ideas/`:

| Checkout | Diary module | Diary tests |
|---|---|---|
| `/work/foodcore/ideas/16/repo` (branch `forge/foodcore/t_cd560d72`, HEAD `c4202f9`) | `app/diary.py` — module `foodcore.diary`: `LogEntry`, `undo_handler_for`, `save_handler_for`, `delete_handler_for`, `LogToast`, `EditSheet` | `tests/test_diary.py` (18 tests) |
| `/work/foodcore/ideas/9/repo` (branch `forge/foodcore/t_8ff0a241`, HEAD `05dbaaf`) | `app/diary.py` — module `foodcore.diary`: `LogAgainRow`, `LogAgainChip`, `log_again_write`, `LogToast`, `logged_after_write`; plus `app/store.py` — module `foodcore.store` | `tests/test_diary.py` (14), `tests/test_store.py` |
| `/work/foodcore/ideas/7/repo` (branch `forge/foodcore/t_ec871437`, HEAD `5fa8b1f`) | `app/diary/` package — module `foodcore.diary.db` (`init_db`, `add_entry`, `list_entries`, `get_entry`, `update_entry`, `delete_entry`, `import_csv`, `day_totals`) + `app/cli.py` `diary` subcommands | `tests/test_diary.py` (12), `tests/test_roundtrip.py` (2); fixture `tests/fixtures/sample.csv` |
| `/work/foodcore/ideas/8/repo` (branch `forge/foodcore/t_13c1e1cd`, HEAD `87712f4`) | `app/store.py` — module `foodcore.store`; `app/importer.py` — module `foodcore.importer` | `tests/test_store.py` (11), `tests/test_import.py` (5) |

## Recorded facts for the follow-up tasks

- Diary module path: `app/diary.py` / `app/diary/` / `app/store.py` / `app/importer.py`
  (imported as `foodcore.diary`, `foodcore.store`, `foodcore.importer`).
- Diary test file path: `tests/test_diary.py` in the diary-bearing checkouts, plus
  the sibling diary test files (`test_store.py`, `test_import.py`, `test_roundtrip.py`).
- Existing test runner / gate: `python -m pytest -q` (pytest, `dev` extra
  `pytest>=8.0`; `[tool.pytest.ini_options] testpaths = ["tests"]`), lint
  `ruff check .`, CI (`.github/workflows/ci.yml`) = `ruff check .` + `python -m pytest -q`
  on a Python 3.10/3.12 matrix plus a clean-venv install acceptance job.

## How the diary handlers are invoked

- Toast / inline-edit-sheet handlers are injected callables. The toast mints them
  with `undo_handler_for(entry, remove=...)`; the sheet with `save_handler_for(save=...)`
  and `delete_handler_for(entry, remove=...)`; the sheet then calls
  `save_edits()` / `delete_entry()` / `edited_entry()`. `LogToast.after_log(...,
  undo=..., window_seconds=..., now=..., undo_label=...)` and
  `LogToast.confirm(now=...)` carry the auto-expiry window and the frozen clock
  (`now=`) the follow-up invariant tests will drive.
- Store handlers are module functions that take the connection from the caller:
  `init_db(db=...)`, `add_entry(..., db=...)`, `get_entries(...)`, `get_top_used(...)`,
  `record_use(...)`, `import_csv(...)`, `day_totals(db=...)`.
- CLI handlers are bound in `app/cli.py` behind the `diary` subparser group:
  `python3 -m foodcore.cli diary add|list|edit|delete|import`.

## Finding

The diary code and its tests **do exist** — in the diary-bearing checkouts listed
above, not in this task's own workspace checkout. The workspace checkout itself is
pre-diary, so for the follow-up ("add the frozen-clock undo/re-log invariant
harness in the diary test file") the diary test file to extend is the one that
already exists in a diary-bearing checkout, and the diary gate is that checkout's
`python -m pytest -q`.
