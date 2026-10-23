"""Shopping list aggregation across recipes.

Takes one or more RecipeLine objects (from nutrition.py) and aggregates them
into a consolidated shopping list: one entry per distinct food, amounts summed
in a common unit via convert(), each entry carrying combined Resolved provenance
(weakest method/confidence across its contributing lines) or an explicit
Unresolved when lines for the same food cannot be reconciled into one unit.

This is for myMeal/Edibl: a user picks several recipes for the week and wants
one shopping list, not N separate ingredient lists with overlapping items they
have to merge by hand.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

from .convert import convert
from .datasets import FoodRecord
from .nutrition import RecipeLine
from .provenance import Provenance, Resolved, Unresolved


@dataclass(frozen=True)
class ShoppingItem:
    """One aggregated ingredient line for the shopping list.

    ``food`` is the canonical food identifier (e.g. "usda:168894").
    ``label`` is the user-facing name (e.g. "all-purpose flour").
    ``amount`` is the total quantity after aggregation.
    ``unit`` is the common unit used for reporting.
    ``provenance`` describes how this aggregated value was computed.
    ``unresolved_reason`` is set when lines could not be merged (e.g. incompatible units).
    ``unresolved_detail`` explains what would fix the unmergeable case.
    ``contributing_lines`` lists the original recipe line labels that contributed.
    ``on_hand_covered`` is True when on-hand inventory fully covers this item.
    ``unresolved_on_hand_reason`` is set when on-hand unit cannot be converted to item unit.
    """

    food: str
    label: str
    amount: float | None
    unit: str
    provenance: Provenance | None
    unresolved_reason: str | None = None
    unresolved_detail: str | None = None
    contributing_lines: tuple[str, ...] = ()
    on_hand_covered: bool = False
    unresolved_on_hand_reason: str | None = None


@dataclass(frozen=True)
class ShoppingList:
    """A consolidated shopping list built from one or more recipes."""

    items: tuple[ShoppingItem, ...]
    recipe_labels: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)


def merge_lines(
    lines: Sequence[RecipeLine], *, dataset, version: str
) -> ShoppingList:
    """Aggregate ingredient lines from one or more recipes into a shopping list.

    Args:
        lines: RecipeLine objects to aggregate. Can come from multiple recipes.
        dataset: The reference Dataset instance for unit conversion and food lookups.
        version: The algorithm version string (e.g., foodcore.rule_version("convert")).

    Returns:
        A ShoppingList with one entry per distinct food. Lines for the same food
        are merged when they share a common unit or can be converted to one.
        Incompatible unit cases return Unresolved with a clear reason.

    Raises:
        ValueError: If lines is None or version is empty.
    """
    if lines is None:
        raise ValueError("lines cannot be None")
    if not version:
        raise ValueError("version is required")

    # Group lines by food identifier
    food_groups: dict[str, list[RecipeLine]] = {}
    for line in lines:
        # Extract food identifier from composition
        if isinstance(line.composition, Resolved):
            food_id = line.composition.source_id
        elif isinstance(line.composition, Unresolved):
            # For unresolved compositions, use the label as fallback
            food_id = f"unresolved:{line.label}"
        else:
            # Composition is a Composition object
            food_id = line.composition.food_id

        if food_id not in food_groups:
            food_groups[food_id] = []
        food_groups[food_id].append(line)

    items: list[ShoppingItem] = []

    for food_id, group in food_groups.items():
        item = _aggregate_group(food_id, group, dataset=dataset, version=version)
        items.append(item)

    # Extract unique recipe labels from the input lines
    recipe_labels = tuple(
        sorted(set(_get_recipe_label(line) for line in lines if _get_recipe_label(line)))
    )

    return ShoppingList(items=tuple(items), recipe_labels=recipe_labels)


def _get_recipe_label(line: RecipeLine) -> str | None:
    """Extract the recipe label from a RecipeLine.

    The RecipeLine doesn't directly store its parent recipe label,
    so we look for it in the label or return None.
    """
    # Try to extract from label format like "Recipe Name: ingredient"
    if ":" in line.label:
        parts = line.label.split(":", 1)
        if len(parts) == 2 and parts[0].strip():
            return parts[0].strip()
    return None


def _get_food_record(food_id: str, dataset) -> FoodRecord | None:
    """Get a FoodRecord from the dataset for a given food_id."""
    if dataset is None:
        return None
    # Try to get the food record directly
    try:
        return dataset.food_record(food_id)
    except Exception:
        # If that fails, try without the provider prefix
        if ":" in food_id:
            short_id = food_id.split(":", 1)[-1]
            try:
                return dataset.food_record(short_id)
            except Exception:
                pass
        return None


def _aggregate_group(
    food_id: str, lines: list[RecipeLine], *, dataset, version: str
) -> ShoppingItem:
    """Aggregate lines for a single food into one ShoppingItem.

    Args:
        food_id: The canonical food identifier.
        lines: RecipeLine objects for the same food.
        dataset: The reference Dataset instance.
        version: The algorithm version string.

    Returns:
        A ShoppingItem with aggregated values or an Unresolved if merge is impossible.
    """
    if not lines:
        return ShoppingItem(
            food=food_id,
            label=food_id,
            amount=0.0,
            unit="",
            provenance=None,
        )

    # Get the food record for conversion (if dataset is available)
    food_record = _get_food_record(food_id, dataset)

    # Collect all amounts and units
    amount_unit_pairs: list[tuple[float, str, RecipeLine]] = []
    unresolved_reasons: list[Unresolved] = []

    for line in lines:
        if isinstance(line.edible_grams, Resolved):
            amount_unit_pairs.append((line.edible_grams.value, line.edible_grams.unit, line))
        elif isinstance(line.edible_grams, Unresolved):
            unresolved_reasons.append(line.edible_grams)

    # If all lines are unresolved for grams, return Unresolved
    if len(amount_unit_pairs) == 0 and unresolved_reasons:
        reasons = [u.reason for u in unresolved_reasons]
        details = [u.detail for u in unresolved_reasons]
        return ShoppingItem(
            food=food_id,
            label=lines[0].label if lines else food_id,
            amount=None,
            unit="",
            provenance=None,
            unresolved_reason="all_unresolved",
            unresolved_detail=f"Cannot determine weights: {'; '.join(details)}",
            contributing_lines=tuple(line.label for line in lines),
        )

    # If no lines have resolved grams, return Unresolved
    if not amount_unit_pairs:
        return ShoppingItem(
            food=food_id,
            label=lines[0].label if lines else food_id,
            amount=None,
            unit="",
            provenance=None,
            unresolved_reason="no_grams",
            unresolved_detail="None of the lines have a resolved weight",
            contributing_lines=tuple(line.label for line in lines),
        )

    # Check if all units are the same
    units = {unit for _, unit, _ in amount_unit_pairs}
    if len(units) == 1:
        # All same unit - just sum them
        total_amount = sum(amount for amount, _, _ in amount_unit_pairs)
        unit = list(units)[0]

        # Build combined provenance from all contributing lines
        provs = []
        for _, _, line in amount_unit_pairs:
            if isinstance(line.edible_grams, Resolved):
                provs.append(line.edible_grams.provenance)

        combined_prov = _combine_provenances(provs, method="calculated", version=version)

        return ShoppingItem(
            food=food_id,
            label=_get_label(lines),
            amount=total_amount,
            unit=unit,
            provenance=combined_prov,
            contributing_lines=tuple(line.label for line in lines),
        )

    # Units differ - try to convert to a common unit
    # Pick 'g' as the target unit for aggregation (grams are the base unit)
    target_unit = "g"
    converted_amounts: list[tuple[float, Provenance]] = []
    conversion_failures: list[tuple[str, str, str]] = []  # (original_unit, reason, detail)

    for amount, unit, line in amount_unit_pairs:
        if unit == target_unit:
            # No conversion needed
            if isinstance(line.edible_grams, Resolved):
                converted_amounts.append((amount, line.edible_grams.provenance))
            else:
                # Shouldn't happen given our filtering, but handle gracefully
                converted_amounts.append((amount, _dummy_provenance(version)))
        else:
            # Try to convert TO the target unit (grams)
            result = convert(amount, unit, target_unit, food=food_record, dataset=dataset)
            if isinstance(result, Resolved):
                converted_amounts.append((result.value, result.provenance))
            else:
                conversion_failures.append((unit, result.reason, result.detail))

    if conversion_failures:
        # Some conversions failed - return Unresolved with details
        reasons = [f"{orig}: {r}" for orig, r, _ in conversion_failures]
        details = [d for _, _, d in conversion_failures]
        return ShoppingItem(
            food=food_id,
            label=_get_label(lines),
            amount=None,
            unit=target_unit,
            provenance=None,
            unresolved_reason="unit_conversion_failed",
            unresolved_detail=f"Could not convert all units to {target_unit}: {'; '.join(details)}",
            contributing_lines=tuple(line.label for line in lines),
        )

    # All conversions succeeded - sum them
    total_amount = sum(amount for amount, _ in converted_amounts)

    # Build combined provenance from all converted values
    provs = [prov for _, prov in converted_amounts]
    combined_prov = _combine_provenances(provs, method="calculated", version=version)

    return ShoppingItem(
        food=food_id,
        label=_get_label(lines),
        amount=total_amount,
        unit=target_unit,
        provenance=combined_prov,
        contributing_lines=tuple(line.label for line in lines),
    )


def _get_label(lines: list[RecipeLine]) -> str:
    """Get a representative label for the aggregated item."""
    if not lines:
        return ""
    # Use the first line's label, or extract just the ingredient part
    label = lines[0].label
    if ":" in label:
        parts = label.split(":", 1)
        if len(parts) == 2:
            return parts[1].strip()
    return label


def _dummy_provenance(version: str) -> Provenance:
    """Create a dummy provenance for fallback cases."""
    return Provenance(
        source="internal",
        source_id="dummy",
        retrieved="1970-01-01T00:00:00Z",
        method="estimated",
        version=version,
        confidence=0.0,
        license="internal",
    )


def _combine_provenances(
    provs: list[Provenance], *, method: str, version: str
) -> Provenance:
    """Combine multiple provenances into one, using weakest-link rules.

    - Method is the weakest (minimum rank) of all inputs
    - Confidence is the product of all confidences (independent errors)
    - Retrieved is the earliest date
    - License is AND-joined
    """
    if not provs:
        return _dummy_provenance(version)

    # Method: weakest link
    from .nutrition import weakest_method

    combined_method = weakest_method(*(p.method for p in provs))

    # Confidence: product (independent errors)
    confidence = 1.0
    for p in provs:
        confidence *= p.confidence

    # Retrieved: earliest date
    retrieved_dates = [p.retrieved for p in provs if p.retrieved]
    retrieved = min(retrieved_dates) if retrieved_dates else "1970-01-01T00:00:00Z"

    # License: AND-join
    licenses = []
    for p in provs:
        if p.license:
            for lic in p.license.split(" AND "):
                lic = lic.strip()
                if lic and lic not in licenses:
                    licenses.append(lic)
    license_str = " AND ".join(sorted(licenses)) if licenses else "internal"

    # Source: use the first non-internal source, or internal
    sources = [p.source for p in provs if p.source != "internal"]
    source = sources[0] if sources else "internal"

    # Source_id: combine all source_ids
    source_ids = [p.source_id for p in provs if p.source_id]
    source_id = "+".join(sorted(set(source_ids))) if source_ids else ""

    return Provenance(
        source=source,
        source_id=source_id,
        retrieved=retrieved,
        method=combined_method,
        version=version,
        confidence=confidence,
        license=license_str,
    )


def _group_on_hand(on_hand: Sequence[tuple[str, float, str]]) -> dict[str, list[tuple[float, str]]]:
    """Group on-hand items by food_id.

    Args:
        on_hand: Sequence of (food_id, amount, unit) tuples.

    Returns:
        Dict mapping food_id to list of (amount, unit) tuples.
    """
    grouped: dict[str, list[tuple[float, str]]] = {}
    for food_id, amount, unit in on_hand:
        if food_id not in grouped:
            grouped[food_id] = []
        grouped[food_id].append((amount, unit))
    return grouped


def subtract_on_hand(
    shopping_list: ShoppingList,
    on_hand: Sequence[tuple[str, float, str]],
    *,
    dataset,
    version: str,
) -> ShoppingList:
    """Subtract on-hand pantry/fridge inventory from a shopping list.

    Args:
        shopping_list: A ShoppingList (typically from merge_lines) to reduce.
        on_hand: Sequence of (food_id, amount, unit) tuples representing items
                 already owned by the user.
        dataset: The reference Dataset instance for unit conversion.
        version: The algorithm version string (e.g., foodcore.rule_version("convert")).

    Returns:
        A new ShoppingList where each item's amount is reduced by on-hand stock.
        Items fully covered by on-hand stock get on_hand_covered=True.
        Items that cannot be unit-converted keep their original amount and get
        unresolved_on_hand_reason="on_hand_unit_mismatch".

    Notes:
        - Items are matched by food_id (e.g., "usda:168894").
        - Unit conversion uses the same convert() logic as merge_lines.
        - Items fully covered by on-hand stock keep their line but get
          on_hand_covered=True so host apps can show "have enough: flour"
          instead of silently removing the line.
        - Items that cannot be converted to a common unit keep their original
          amount and get unresolved_on_hand_reason so discrepancies are visible.
    """
    if not version:
        raise ValueError("version is required")

    # Group on-hand items by food_id
    on_hand_by_food = _group_on_hand(on_hand)

    new_items: list[ShoppingItem] = []

    for item in shopping_list.items:
        # Skip items without a valid food_id or amount
        if not item.food or item.amount is None:
            new_items.append(item)
            continue

        # Check if we have on-hand inventory for this food
        if item.food not in on_hand_by_food:
            # No on-hand inventory for this food
            new_items.append(item)
            continue

        # Process on-hand inventory for this food
        on_hand_items = on_hand_by_food[item.food]
        remaining_amount = item.amount

        for on_hand_amount, on_hand_unit in on_hand_items:
            if remaining_amount <= 0:
                # Already fully covered, skip remaining on-hand items
                break

            if on_hand_amount <= 0:
                # Skip invalid on-hand amounts
                continue

            # Try to convert on-hand unit to item's unit
            food_record = _get_food_record(item.food, dataset)
            result = convert(on_hand_amount, on_hand_unit, item.unit, food=food_record, dataset=dataset)

            if isinstance(result, Resolved):
                # Successfully converted - subtract
                remaining_amount -= result.value
            else:
                # Conversion failed - mark as unresolved and keep original amount
                new_items.append(
                    ShoppingItem(
                        food=item.food,
                        label=item.label,
                        amount=item.amount,
                        unit=item.unit,
                        provenance=item.provenance,
                        unresolved_reason=item.unresolved_reason,
                        unresolved_detail=item.unresolved_detail,
                        contributing_lines=item.contributing_lines,
                        on_hand_covered=False,
                        unresolved_on_hand_reason="on_hand_unit_mismatch",
                    )
                )
                break
        else:
            # All on-hand items processed successfully
            if remaining_amount <= 0:
                # Fully covered by on-hand inventory
                new_items.append(
                    ShoppingItem(
                        food=item.food,
                        label=item.label,
                        amount=0.0,
                        unit=item.unit,
                        provenance=item.provenance,
                        unresolved_reason=item.unresolved_reason,
                        unresolved_detail=item.unresolved_detail,
                        contributing_lines=item.contributing_lines,
                        on_hand_covered=True,
                        unresolved_on_hand_reason=None,
                    )
                )
            else:
                # Partially covered - reduce amount
                new_items.append(
                    ShoppingItem(
                        food=item.food,
                        label=item.label,
                        amount=max(0.0, remaining_amount),
                        unit=item.unit,
                        provenance=item.provenance,
                        unresolved_reason=item.unresolved_reason,
                        unresolved_detail=item.unresolved_detail,
                        contributing_lines=item.contributing_lines,
                        on_hand_covered=False,
                        unresolved_on_hand_reason=None,
                    )
                )

    return ShoppingList(
        items=tuple(new_items),
        recipe_labels=shopping_list.recipe_labels,
    )


__all__ = [
    "ShoppingItem",
    "ShoppingList",
    "merge_lines",
    "subtract_on_hand",
]
