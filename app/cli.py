"""``python3 -m foodcore.cli`` — build and inspect a reference dataset.

Three commands, all run by an operator (or a host app's import job), never in a
request path:

    python3 -m foodcore.cli build-usda --fdc-dir ./FoodData_Central_csv \\\\
        --out /config/mymeal/foodcore.sqlite --dataset-version "April 2025"

    python3 -m foodcore.cli info --dataset /config/mymeal/foodcore.sqlite

    python3 -m foodcore.cli lookup <query> [--dataset ...] [--limit ...] \
        [--measure cup] [--nutrient energy]

``--dataset-version`` and ``--retrieved`` are **required** for a build because
they become ``Provenance.dataset_version`` / ``retrieved`` on every value the
file yields. A dataset that cannot say which snapshot it is cannot be cited,
and an uncitable value is one this package will not serve.

The ``lookup`` subcommand exercises the same resolution logic that host apps
use via ``resolve_food()`` and ``search_foods()``, letting developers sanity-
check what a given dataset returns for a food name without writing a throwaway
Python script.
"""
from __future__ import annotations

import argparse
import datetime
import sys

from .datasets import DatasetError, build_dataset, load_dataset


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

    lookup = sub.add_parser(
        "lookup",
        help="resolve or search for a food name against the dataset",
    )
    lookup.add_argument("query", help="the food name to look up")
    lookup.add_argument("--dataset", default=None,
                        help="path to the dataset (default: $FOODCORE_DATASET, "
                             "else the bundled minimal one)")
    lookup.add_argument("--measure", default=None, metavar="MEASURE",
                        help="also resolve this household measure (e.g. cup) "
                             "through portion_grams and print its Outcome")
    lookup.add_argument("--nutrient", default=None, metavar="NUTRIENT",
                        help="also resolve this nutrient (e.g. energy) through "
                             "nutrient_per_100g and print its Outcome")
    lookup.add_argument("--limit", type=int, default=10,
                        help="max candidates to show for ambiguous queries (default: 10)")

    args = parser.parse_args(argv)
    if args.command == "build-usda":
        return _build_usda(args)
    if args.command == "info":
        return _info(args)
    return _lookup(args)


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


def _lookup(args) -> int:
    """Resolve or search for a food name and print the result."""
    from . import rule_version  # the package __init__; keeps import-time lean

    try:
        dataset = load_dataset(args.dataset)
    except DatasetError as exc:
        print(f"foodcore: {exc}", file=sys.stderr)
        return 1

    # First try resolve_food (confidence-tiered resolution)
    match = dataset.resolve_food(args.query)

    if not match.candidates:
        # Zero matches
        print(f"No matches for {args.query!r}")
        return 0

    if match.confident:
        # Confident match: print the resolved food with its portions and provenance
        food = match.food
        assert food is not None  # for type checker
        print(f"Resolved: {food.description} [{food.provider}:{food.source_id}]")
        if food.portions:
            print("Portions:")
            for p in sorted(food.portions, key=lambda x: (x.measure, x.size or "", x.qualifier or "")):
                parts = [p.measure]
                if p.size:
                    parts.append(f"size={p.size}")
                if p.qualifier:
                    parts.append(f"qualifier={p.qualifier}")
                print(f"  {' '.join(parts)}: {p.gram_weight} g ({p.method}, {p.confidence:.0%})")
        else:
            print("Portions: none published")

        # Nutrients if available
        if food.nutrients:
            print("Nutrients (per 100 g):")
            for nutrient, (amount, unit) in sorted(food.nutrients.items()):
                print(f"  {nutrient}: {amount} {unit}")
        else:
            print("Nutrients: none published")

        # --measure / --nutrient: ask the same engines the host apps call, so
        # this prints exactly what a host would get — provenance included.
        if args.measure:
            outcome = dataset.portion_grams(
                food.key, args.measure, version=rule_version("convert"))
            _print_outcome(f"Measure {args.measure!r}", outcome)
        if args.nutrient:
            outcome = dataset.nutrient_per_100g(
                food.key, args.nutrient, version=rule_version("nutrition"))
            _print_outcome(f"Nutrient {args.nutrient!r}", outcome)
    else:
        # Ambiguous: show candidates like FoodMatch.describe()
        print(f"Ambiguous: {len(match.candidates)} candidates for {args.query!r}")
        limit = min(args.limit, len(match.candidates))
        for i, (food, score) in enumerate(match.candidates[:limit], 1):
            states = "/".join(sorted(food.states)) or "unspecified"
            print(f"  {i}. {food.source_id} {food.description} [{states}] score={score}")
        if len(match.candidates) > limit:
            print(f"  ... and {len(match.candidates) - limit} more")

    return 0


def _print_outcome(label: str, outcome) -> None:
    """One Outcome → one printed line; unresolved answers print their reason."""
    if outcome.resolved:
        prov = outcome.provenance
        print(f"{label}: {outcome.value:g} {outcome.unit} "
              f"([{prov.source}:{prov.source_id}] {prov.method}, "
              f"{prov.confidence:.0%}, {prov.version}, {prov.license})")
    else:
        print(f"{label}: unresolved [{outcome.reason}] {outcome.detail}")


if __name__ == "__main__":
    sys.exit(main())
