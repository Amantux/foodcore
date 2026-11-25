"""``python3 -m foodcore.cli`` — build and inspect a reference dataset, drive the diary.

Three command groups, all run by an operator (or a host app's import job), never in a
request path:

    python3 -m foodcore.cli build-usda --fdc-dir ./FoodData_Central_csv \\
        --out /config/mymeal/foodcore.sqlite --dataset-version "April 2025"

    python3 -m foodcore.cli info --dataset /config/mymeal/foodcore.sqlite

``--dataset-version`` and ``--retrieved`` are **required** for a build because
they become ``Provenance.dataset_version`` / ``retrieved`` on every value the
file yields. A dataset that cannot say which snapshot it is cannot be cited,
and an uncitable value is one this package will not serve.
"""
from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys

from .datasets import DatasetError, build_dataset, load_dataset
from .diary import add_entry, day_totals, delete_entry, import_csv, init_db, list_entries, update_entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m foodcore.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser(
        "build-usda",
        help="turn a USDA FoodData Central CSV export into a compact dataset file",
    )
    build.add_argument("--fdc-dir", required=True,
                       help="directory containing food.csv, food_portion.csv, …")
    build.add_argument("--out", required=True, help="dataset file to write")
    build.add_argument("--dataset-version", required=True,
                       help='upstream release id, e.g. "April 2025" — it is cited '
                            "in every value's provenance")
    build.add_argument("--retrieved", default=datetime.date.today().isoformat(),
                       help="ISO date this export was downloaded (default: today)")
    build.add_argument("--data-type", action="append", default=[],
                       help="limit to an FDC data_type (repeatable), e.g. "
                            "foundation_food. Default: everything in the export")
    build.add_argument("--limit", type=int, default=None,
                       help="stop after N foods (for a quick trial build)")

    info = sub.add_parser("info", help="describe a dataset file")
    info.add_argument("--dataset", default=None,
                      help="path to the dataset (default: $FOODCORE_DATASET, "
                           "else the bundled minimal one)")

    diary = sub.add_parser(
        "diary",
        help="the household food diary: add / list / edit / delete / import",
    )
    diary_commands = diary.add_subparsers(dest="diary_command", required=True)

    diary_list = diary_commands.add_parser(
        "list",
        help="list entries, newest first, grouped by day, with each day's kcal total",
    )
    diary_list.add_argument(
        "--db",
        default=None,
        help="diary store file (default: the diary's own store)",
    )

    diary_add = diary_commands.add_parser(
        "add",
        help="add one eating occasion",
    )
    diary_add.add_argument("title", help="what was eaten, e.g. \"Chicken stir-fry\"")
    diary_add.add_argument("--kind", default="food", choices=("meal", "food"),
                           help="meal slot or standalone food (default: food)")
    diary_add.add_argument("--note", default=None, help="free text")
    diary_add.add_argument("--kcal", type=float, default=None,
                           help="kcal for the eating occasion; omit when unmeasured")
    diary_add.add_argument("--tags", default=None, help="comma-separated tags")
    diary_add.add_argument("--when", default=None,
                            help="ISO datetime of the meal (default: now)")
    diary_add.add_argument("--db", default=None, help="diary store file")

    diary_edit = diary_commands.add_parser(
        "edit",
        help="update the fields of a diary entry",
    )
    diary_edit.add_argument("entry_id", type=int, help="id of the entry to edit")
    diary_edit.add_argument("--when", default=None, help="ISO datetime of the meal")
    diary_edit.add_argument("--kind", default=None, choices=("meal", "food"),
                             help="meal slot or standalone food")
    diary_edit.add_argument("--title", default=None, help="what was eaten")
    diary_edit.add_argument("--note", default=None, help="free text")
    diary_edit.add_argument("--kcal", type=float, default=None, help="kcal")
    diary_edit.add_argument("--tags", default=None, help="comma-separated tags")
    diary_edit.add_argument("--db", default=None, help="diary store file")

    diary_delete = diary_commands.add_parser(
        "delete",
        help="delete a diary entry",
    )
    diary_delete.add_argument("entry_id", type=int, help="id of the entry to delete")
    diary_delete.add_argument("--db", default=None, help="diary store file")

    diary_import = diary_commands.add_parser(
        "import",
        help="import a diary CSV (when,title,kcal)",
    )
    diary_import.add_argument("path", help="path to the diary CSV to import")
    diary_import.add_argument("--db", default=None, help="diary store file")

    args = parser.parse_args(argv)
    if args.command == "build-usda":
        return _build_usda(args)
    if args.command == "info":
        return _info(args)
    if args.command == "diary":
        return _diary(args)
    return 2


def _build_usda(args) -> int:
    # Imported here, not at module scope: the adapter is only needed by a build,
    # and `foodcore.cli info` must work on a host that never imports a parser.
    from .sources.usda import UsdaImportError, load_fdc_csv

    # BOTH halves are inside the try. The parse half was guarded and the
    # STORAGE half was not, so `--out` pointing at a non-existent directory
    # printed a raw `sqlite3.OperationalError` traceback — the exact thing the
    # comment below says this does not do. A ValueError from a malformed row
    # escaped the same way, printing the whole row.
    try:
        export = load_fdc_csv(
            args.fdc_dir,
            version=args.dataset_version,
            retrieved=args.retrieved,
            data_types=tuple(args.data_type) or None,
            limit=args.limit,
        )
        foods, portions, nutrients = export.rows()
        counts = build_dataset(
            args.out,
            sources=[export.source_record()],
            foods=foods,
            portions=portions,
            nutrients=nutrients,
            builder="foodcore.cli build-usda",
        )
    except (UsdaImportError, DatasetError, ValueError) as exc:
        # Typed domain exceptions with curated messages — not a raw traceback,
        # not the csv module's text, and not the sqlite3 driver's.
        print(f"foodcore: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {args.out}")
    print(export.stats.report())
    print("rows: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    # The parser's count and the file's count must agree. When they do not,
    # rows collapsed on a primary key, and the operator is the only one who can
    # decide whether that matters — so say it rather than printing two numbers
    # and hoping somebody compares them.
    expected = {"foods": len(foods), "portions": len(portions),
                "nutrients": len(nutrients)}
    collapsed = {k: (v, counts[k]) for k, v in expected.items() if counts[k] != v}
    if collapsed:
        print("NOTE: rows collapsed on a primary key (parsed -> stored): "
              + ", ".join(f"{k} {a}->{b}" for k, (a, b) in sorted(collapsed.items())),
              file=sys.stderr)
    return 0


def _info(args) -> int:
    try:
        dataset = load_dataset(args.dataset)
    except DatasetError as exc:
        print(f"foodcore: {exc}", file=sys.stderr)
        return 1
    where = "bundled minimal dataset" if dataset.path is None else dataset.path
    print(f"dataset:        {where}")
    print(f"schema version: {dataset.schema_version}")
    if dataset.is_minimal:
        print("NOTE: this is the bundled fallback — definitional facts only, no "
              "USDA or Open Food Facts data. Household measures will mostly "
              "return 'unresolved' until a real dataset is built.")
    for record in dataset.sources:
        print(
            f"source:         {record.provider} {record.dataset_version} "
            f"(retrieved {record.retrieved_at}, {record.license}, "
            f"{record.record_count} records)"
        )
    return 0


def _diary(args) -> int:
    if args.diary_command == "list":
        return _diary_list(args)
    if args.diary_command == "add":
        return _diary_add(args)
    if args.diary_command == "edit":
        return _diary_edit(args)
    if args.diary_command == "delete":
        return _diary_delete(args)
    return _diary_import(args)


def _diary_list(args) -> int:
    init_db(db=args.db)
    entries = list_entries(db=args.db)
    totals = day_totals(db=args.db)
    days: dict[str, list[dict]] = {}
    for entry in entries:
        days.setdefault(str(entry["when"])[:10], []).append(entry)
    for day, group in days.items():
        print(day)
        for entry in group:
            moment = str(entry["when"])
            clock = moment[11:16] if len(moment) > 16 else moment
            line = f"  {clock}  {entry['title']}"
            if entry["kcal"] is not None:
                line += f" ({_fmt_kcal(entry['kcal'])} kcal)"
            print(line)
        print(f"  total: {_fmt_kcal(totals.get(day, 0.0))}")
    return 0


def _diary_add(args) -> int:
    try:
        init_db(db=args.db)
        entry_id = add_entry(
            when=args.when or datetime.datetime.now().isoformat(timespec="seconds"),
            title=args.title,
            kind=args.kind,
            note=args.note,
            kcal=args.kcal,
            tags=args.tags,
            source="manual",
            db=args.db,
        )
    except (ValueError, sqlite3.Error) as exc:
        print(f"foodcore: {exc}", file=sys.stderr)
        return 1
    print(f"added entry {entry_id}")
    return 0


def _diary_edit(args) -> int:
    fields = {}
    for key in ("when", "kind", "title", "note", "kcal", "tags"):
        value = getattr(args, key, None)
        if value is not None:
            fields[key] = value
    try:
        init_db(db=args.db)
        updated = update_entry(args.entry_id, fields, db=args.db)
    except (ValueError, sqlite3.Error) as exc:
        print(f"foodcore: {exc}", file=sys.stderr)
        return 1
    if updated is None:
        print(f"no entry {args.entry_id}", file=sys.stderr)
        return 1
    print(f"updated entry {args.entry_id}")
    return 0


def _diary_delete(args) -> int:
    try:
        init_db(db=args.db)
        deleted = delete_entry(args.entry_id, db=args.db)
    except (ValueError, sqlite3.Error) as exc:
        print(f"foodcore: {exc}", file=sys.stderr)
        return 1
    if deleted:
        print(f"deleted entry {args.entry_id}")
        return 0
    print(f"no entry {args.entry_id}", file=sys.stderr)
    return 1


def _diary_import(args) -> int:
    try:
        init_db(db=args.db)
        count = import_csv(args.path, db=args.db)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"foodcore: {exc}", file=sys.stderr)
        return 1
    print(f"imported {count} entries from {args.path}")
    return 0


def _fmt_kcal(value: float) -> str:
    """Render a kcal figure without a trailing ``.0`` on whole numbers."""
    return f"{float(value):g}"


if __name__ == "__main__":
    sys.exit(main())
