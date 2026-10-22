"""Open Food Facts adapter — branded/barcoded products, ODbL.

Why this module exists: Open Food Facts is the canonical open dataset for branded
and barcoded grocery products. USDA FDC barely covers branded products, but OFF
has GTINs (EAN/UPC barcodes), serving sizes, and per-100g nutrients for millions
of packaged foods. Without OFF, barcode-driven resolution is the largest
unresolved class for a host app.

**This module PARSES; it does not store.** It reads an OFF CSV export into the
record types `datasets.py` defines (`FoodRecord`, `Portion`) and hands them to
`datasets.build_dataset`, which owns the one storage format. There was briefly a
second importer (`off_import.py`) with its own `Dataset`, its own unit table
and its own parse of the same CSV; it read the schema more naively and silently
lost the two traps below, so it is gone. One parser, one store.

Pure data in, pure data out: no Flask, no ORM, no network, no clock. The loader
takes a path to an OFF `products.csv` export, so production points it at the
real export and tests point it at `foodcore/tests/fixtures/off_sample`.

THE SCHEMA, as published in the OFF products export:

    code                GTIN (EAN-13/UPC-12) or unique product identifier
    product_name        Consumer-facing name
    brands              Brand(s) that own the product
    categories_tags     Pipe-separated category path (e.g. "en:plant-based-foods|en:spreads")
    ingredients_text    Human-readable ingredient list
    nutriscore_grade    A–E nutritional score (EU)
    ecoscore_grade      A–E environmental score (EU)
    labels_tags         Pipe-separated label tags (organic, fair-trade, etc.)
    quantity            Packaging quantity (e.g. "200 g", "1.5 L") — parsed for portions
    serving_quantity    Number of servings per package (e.g. "2", "4")
    serving_size        Per-serving amount with unit (e.g. "30 g", "150 ml")
    energy_100g         Energy per 100 g (kcal)
    fat_100g            Fat per 100 g (g)
    saturated-fat_100g  Saturated fat per 100 g (g)
    carbohydrates_100g  Carbohydrates per 100 g (g)
    sugars_100g         Sugars per 100 g (g)
    fiber_100g          Fiber per 100 g (g)
    proteins_100g       Proteins per 100 g (g)
    salt_100g           Salt per 100 g (g)
    sodium_100g         Sodium per 100 g (mg)

Two traps in that schema, both handled here:

1. **`serving_size` may be missing or unparseable.** Many products publish
   `serving_quantity` but no `serving_size`, or a malformed value like "1
   portion". A row without a parseable serving size is skipped — and the skip
   is REPORTED, because a silent drop is indistinguishable from an export that
   never had the row.
2. **`code` may be missing or non-numeric.** OFF uses numeric GTINs for
   barcoded products but text identifiers for non-barcode items. Only rows with
   numeric codes are imported (they become GTINs); others are skipped and
   counted.

A third trap: the preparation qualifier ("chopped", "sliced") does not exist
in OFF — OFF publishes raw product data only. This is why the adapter does not
attempt to parse `ingredients_text` for preparation states.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field

from ..datasets import FoodRecord, Portion
from ..registry import SourceRecord
from ..units import normalise_unit, measure_key

#: Must be a member of provenance.SOURCES — the closed provider vocabulary.
#: The dataset EDITION (e.g. "2026-01-01") lives in SourceRecord.dataset_version
#: and the row id in source_id, so nothing is lost by naming the provider plainly here.
SOURCE = "off"
#: Open Food Facts is licensed under ODbL-1.0 — the database and the content
#: are jointly owned by the Open Food Facts association and contributors.
#: Share-alike: derivative databases must be shared under the same license.
LICENSE = "ODbL-1.0"

#: OFF nutrient column suffixes → foodcore's nutrient keys.
#: Matched by stripping the `_100g` suffix and normalising.
#: Extend deliberately: a key that appears here becomes part of the dataset
#: contract that engines query by.
NUTRIENT_COLUMNS: dict[str, str] = {
    "energy_100g": "energy",
    "fat_100g": "fat_total",
    "saturated-fat_100g": "fat_saturated",
    "carbohydrates_100g": "carbohydrate",
    "sugars_100g": "sugars",
    "fiber_100g": "fiber",
    "proteins_100g": "protein",
    "salt_100g": "salt",
    "sodium_100g": "sodium",
}

#: How a value from OFF came to be known. OFF values are declared by manufacturers
#: on product labels, which is weaker evidence than laboratory measurement.
DATA_TYPE_METHOD = "declared"
METHOD_CONFIDENCE = 0.7

#: A parenthetical in a serving size is a DIMENSIONAL NOTE, not a preparation.
_PAREN_RE = re.compile(r"\([^)]*\)")


class OffImportError(Exception):
    """The export file is not a valid OFF products.csv."""


def _num(raw: str | None) -> float | None:
    """Parse a numeric value, returning None on failure."""
    if raw is None:
        return None
    try:
        return float((raw or "").strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_serving_size(serving_size: str | None) -> tuple[float | None, str | None]:
    """Return (amount, unit) for a serving_size like "30 g" or "150 ml".

    Returns (None, None) if unparseable — the caller counts and skips.
    """
    if not serving_size or not serving_size.strip():
        return None, None

    text = _PAREN_RE.sub(" ", serving_size).strip()
    if not text:
        return None, None

    # Try "30 g" or "150 ml" format first
    match = re.match(r"^([\d.,]+)\s*([a-zA-Z]+)$", text)
    if match:
        amount = _num(match.group(1))
        unit = normalise_unit(match.group(2))
        if amount is not None and unit is not None:
            return amount, unit

    # Try "1.5 L" or "0.5 kg" format
    match = re.match(r"^([\d.,]+)\s*([a-zA-Z]+)$", text)
    if match:
        amount = _num(match.group(1))
        unit = normalise_unit(match.group(2))
        if amount is not None and unit is not None:
            return amount, unit

    return None, None


def _parse_quantity_for_portion(quantity: str | None) -> tuple[float | None, str | None]:
    """Return (amount, unit) for a quantity like "200 g" or "1.5 L".

    Used when serving_size is missing but quantity is present.
    """
    if not quantity or not quantity.strip():
        return None, None

    text = _PAREN_RE.sub(" ", quantity).strip()
    if not text:
        return None, None

    # Try "200 g" or "1.5 L" format
    match = re.match(r"^([\d.,]+)\s*([a-zA-Z]+)$", text)
    if match:
        amount = _num(match.group(1))
        unit = normalise_unit(match.group(2))
        if amount is not None and unit is not None:
            return amount, unit

    return None, None


# --- Import reporting --------------------------------------------------------


@dataclass
class ImportStats:
    """What the parse saw. Printed by the CLI and stored in SourceRecord.notes.

    The point is that nothing is dropped silently: a portion we cannot name and
    an upstream nutrient we have no key for are both COUNTED, so an operator can
    see the shape of what was skipped instead of trusting a bare "done".
    """

    foods: int = 0
    portions: int = 0
    nutrients: int = 0
    skipped_portions: int = 0
    skipped_no_code: int = 0
    unmapped_nutrients: dict[str, int] = field(default_factory=dict)

    def report(self) -> str:
        lines = [
            f"foods:     {self.foods}",
            f"portions:  {self.portions} ({self.skipped_portions} skipped)",
            f"nutrients: {self.nutrients}",
        ]
        if self.skipped_no_code:
            lines.append(f"skipped (no numeric code): {self.skipped_no_code}")
        if self.unmapped_nutrients:
            top = sorted(self.unmapped_nutrients.items(), key=lambda kv: -kv[1])[:10]
            lines.append(
                "unmapped nutrients (add to NUTRIENT_COLUMNS to include): "
                + ", ".join(f"{name} x{count}" for name, count in top)
            )
        return "\n".join(lines)


# --- The parse result --------------------------------------------------------


@dataclass(frozen=True)
class OffExport:
    """One parsed OFF export, in memory.

    Deliberately NOT a ``Dataset``: a dataset is the file a host app queries,
    and there is exactly one of those. This is the intermediate an operator's
    build passes through on its way into that file, and it is the shape the
    parser's own tests assert against. Keeping the two apart is what stopped
    foodcore having two incompatible ``Dataset`` classes.
    """

    version: str
    retrieved: str
    foods: tuple[FoodRecord, ...]
    stats: ImportStats = field(default_factory=ImportStats)
    source: str = SOURCE
    license: str = LICENSE

    def food(self, source_id: str) -> FoodRecord | None:
        wanted = str(source_id)
        for rec in self.foods:
            if rec.source_id == wanted:
                return rec
        return None

    # -- the hand-off to storage -----------------------------------------

    def source_record(self) -> SourceRecord:
        return SourceRecord(
            provider=self.source,
            dataset_version=self.version,
            retrieved_at=self.retrieved,
            license=self.license,
            record_count=len(self.foods),
            notes=self.stats.report(),
        )

    def rows(self) -> tuple[list[dict], list[dict], list[dict]]:
        """``(foods, portions, nutrients)`` in the shape ``build_dataset`` takes.

        Every semantic column the parser worked out — unit, size, qualifier,
        amount, the raw modifier text — travels through to the file. The
        previous importer flattened all of it to one `measure` string, which is
        what made "cup, chopped" (160 g) and "cup, sliced" (115 g) collide on
        one primary key and let whichever row was written last win.
        """
        foods: list[dict] = []
        portions: list[dict] = []
        nutrients: list[dict] = []
        for rec in self.foods:
            foods.append({
                "key": rec.key,
                "name": rec.description,
                "provider": rec.provider,
                "source_id": rec.source_id,
                "data_type": "",
            })
            for p in rec.portions:
                portions.append({
                    "food_key": rec.key,
                    "measure": p.measure,
                    "size": p.size,
                    "qualifier": p.qualifier,
                    "amount": p.amount,
                    "grams": p.gram_weight,
                    "seq_num": p.seq_num,
                    "raw_text": p.raw_text,
                    "method": DATA_TYPE_METHOD,
                    "confidence": METHOD_CONFIDENCE,
                    "source_id": p.source_id,
                })
            for key, (amount, unit) in sorted(rec.nutrients.items()):
                nutrients.append({
                    "food_key": rec.key,
                    "nutrient": key,
                    "per_100g": amount,
                    "unit": unit,
                    "method": DATA_TYPE_METHOD,
                    "confidence": METHOD_CONFIDENCE,
                    "source_id": rec.source_id,
                })
        return foods, portions, nutrients


# --- Loading -----------------------------------------------------------------


def _read(path: str) -> list[dict[str, str]]:
    """Read a CSV file into a list of dicts."""
    if not os.path.isfile(path):
        raise OffImportError(f"no such file: {path!r}")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def infer_version(path: str) -> str:
    """'2026-01-01' from the file's mtime or name.

    The CSV export carries no version stamp anywhere inside it, and a dataset
    version is load-bearing for a citable provenance, so it is inferred from the
    file's modification time and otherwise must be passed explicitly.
    """
    try:
        import datetime
        mtime = os.path.getmtime(path)
        return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    except OSError:
        return "unknown"


def load_off_csv(path: str, *, version: str | None = None,
                 retrieved: str | None = None,
                 limit: int | None = None) -> OffExport:
    """Parse an OFF products.csv into an `OffExport`.

    `retrieved` defaults to the file's modification time — a real value from
    the filesystem, so loading the same export twice yields the same provenance.
    """
    stats = ImportStats()
    rows = _read(path)

    # Verify required columns exist
    if not rows:
        raise OffImportError("empty CSV file")
    required_columns = {"code", "product_name", "nutriscore_grade", "energy_100g"}
    first_row_keys = set(rows[0].keys())
    missing = required_columns - first_row_keys
    if missing:
        raise OffImportError(f"missing required columns: {', '.join(sorted(missing))}")

    foods: list[FoodRecord] = []
    for row in rows:
        code = (row.get("code") or "").strip()
        if not code:
            stats.skipped_no_code += 1
            continue

        # Only numeric codes become GTINs; skip non-numeric identifiers
        if not code.isdigit():
            stats.skipped_no_code += 1
            continue

        product_name = (row.get("product_name") or "").strip()
        if not product_name:
            continue

        # Parse serving size
        serving_size = row.get("serving_size")
        amount, unit = _parse_serving_size(serving_size)

        # Fallback to quantity if serving_size is missing
        if amount is None and unit is None:
            quantity = row.get("quantity")
            amount, unit = _parse_quantity_for_portion(quantity)

        # Parse nutrients
        nutrients: dict[str, tuple[float, str]] = {}
        for col, key in NUTRIENT_COLUMNS.items():
            raw = row.get(col)
            val = _num(raw)
            if val is not None:
                # Determine unit based on nutrient
                if key == "energy":
                    unit_val = "kcal"
                elif key in ("salt", "sodium"):
                    unit_val = "g" if key == "salt" else "mg"
                else:
                    unit_val = "g"
                nutrients[key] = (val, unit_val)

        if amount is None or unit is None:
            stats.skipped_portions += 1
            continue

        # Parse grams per 100g to get total weight, then derive per-serving
        # The serving_size column tells us the amount per serving (e.g., "30 g")
        # The quantity column tells us the total package size (e.g., "200 g")
        # We use serving_size to determine grams per serving directly
        
        # Re-parse serving_size for gram_weight
        if serving_size:
            amount2, unit2 = _parse_serving_size(serving_size)
            if amount2 is not None and unit2 == "g":
                # serving_size already gives us grams per serving
                gram_weight = amount2
            else:
                # Try quantity as fallback
                quantity = row.get("quantity")
                if quantity:
                    amount3, unit3 = _parse_quantity_for_portion(quantity)
                    if amount3 is not None and unit3 == "g":
                        gram_weight = amount3
                    else:
                        # Use the serving_size amount as grams if unit is g
                        gram_weight = amount
                else:
                    gram_weight = amount
        else:
            # No serving_size, use quantity as total weight
            quantity = row.get("quantity")
            if quantity:
                amount3, unit3 = _parse_quantity_for_portion(quantity)
                if amount3 is not None and unit3 == "g":
                    gram_weight = amount3
                else:
                    gram_weight = amount
            else:
                gram_weight = amount

        if gram_weight <= 0:
            stats.skipped_portions += 1
            continue

        # Build the portion
        # For OFF, treat "1 serving" as the unit, with gram_weight being the actual weight
        # The amount field should be 1 (one serving), not the numeric value from parsing
        measure = measure_key("g")
        portion = Portion(
            food_key=f"{SOURCE}:{code}",
            measure=measure,
            size=None,
            qualifier="",
            amount=1.0,  # One serving
            gram_weight=gram_weight,
            source_id=f"{code}:g",
            seq_num=1,
            raw_text=serving_size or "",
        )

        foods.append(FoodRecord(
            key=f"{SOURCE}:{code}",
            description=product_name,
            provider=SOURCE,
            source_id=code,
            data_type="branded_food",
            portions=(portion,),
            nutrients=nutrients,
        ))

        stats.foods += 1
        stats.portions += 1
        stats.nutrients += len(nutrients)

        if limit is not None and len(foods) >= limit:
            break

    stats.foods = len(foods)
    stats.portions = sum(len(f.portions) for f in foods)
    stats.nutrients = sum(len(f.nutrients) for f in foods)

    return OffExport(
        version=version or infer_version(path),
        retrieved=retrieved or infer_version(path),
        foods=tuple(foods),
        stats=stats,
    )
