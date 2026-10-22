"""Ingredient-line nutrition query engine.

Public API for hosts (myMeal chat, Edibl) to ask single-ingredient questions
like "how much protein in 2 eggs?" or need per-ingredient nutrition while
importing a recipe.

The function takes an ingredient text line ("2 cups chopped canned tomatoes")
and returns per-nutrient Outcomes - each either Resolved (nutrient-gram value
plus provenance) or Unresolved (machine-readable reason, human detail) - for
one requested nutrient or for all registered nutrients.

The host goes from raw string to a citable answer in one call.
"""
from __future__ import annotations

from typing import Iterable

from .convert import convert_text
from .datasets import Dataset, FoodRecord
from .nutrition import (
    ALGORITHM_VERSION,
    BASIS_UNSPECIFIED,
    Composition,
    NUTRIENTS,
    NutrientAmount,
    weakest_method,
)
from .provenance import Provenance, Resolved, Unresolved

#: The rule version for this module's output.
LINE_QUERY_VERSION = "line_query/1"


def _normalize_nutrient_id(nutrient_id: str) -> str:
    """Map USDA nutrient IDs to foodcore nutrient IDs.

    The USDA database uses 'energy' but foodcore uses 'calories'.
    This function normalizes the ID to match foodcore's convention.
    """
    # Map USDA nutrient IDs to foodcore IDs
    mapping = {
        "energy": "calories",
    }
    return mapping.get(nutrient_id, nutrient_id)


def _resolve_food(
    food_text: str, dataset: Dataset
) -> tuple[FoodRecord | None, Resolved | Unresolved | None]:
    """Resolve a food name to a FoodRecord, or state why not.

    Returns (food_record, None) on success, or (None, Unresolved) on failure.
    """
    match = dataset.resolve_food(food_text)
    if not match.confident:
        if not match.candidates:
            return None, Unresolved(
                reason="unknown_food",
                detail=f"no food in the reference dataset matches {food_text!r}",
            )
        return None, Unresolved(
            reason="ambiguous_food",
            detail=(
                f"{food_text!r} matches several distinct foods; say which: "
                f"{match.describe()}"
            ),
        )
    return match.food, None


def _get_grams(
    text: str, dataset: Dataset
) -> tuple[float | None, Resolved | Unresolved]:
    """Convert an ingredient line to grams, or state why not.

    Returns (grams, None) on success, or (None, Unresolved) on failure.
    """
    result = convert_text(text, "g", dataset=dataset)
    if isinstance(result, Unresolved):
        return None, result
    return result.value, result


def _get_nutrient_per_100g(
    food: FoodRecord, nutrient_id: str, dataset: Dataset
) -> tuple[NutrientAmount | None, Resolved | Unresolved | None]:
    """Get the per-100g nutrient value for a food, or state why not.

    Returns (NutrientAmount, None) on success, or (None, Unresolved) on failure.
    """
    outcome = dataset.nutrient_per_100g(food.key, nutrient_id, version=LINE_QUERY_VERSION)
    if isinstance(outcome, Unresolved):
        return None, outcome

    # Convert to the canonical unit for this nutrient
    nutrient_def = NUTRIENTS.get(nutrient_id)
    if nutrient_def is None:
        # Unknown nutrient id - use the unit from the dataset
        return NutrientAmount(outcome.value, outcome.unit), None

    # Check if conversion is needed
    if outcome.unit.lower() == nutrient_def.unit.lower():
        return NutrientAmount(outcome.value, outcome.unit), None

    # Need to convert units
    from .nutrition import _convert

    converted = _convert(outcome.value, outcome.unit, nutrient_def.unit)
    if converted is None:
        return None, Unresolved(
            reason="unit_conflict",
            detail=f"cannot express {nutrient_id} in {outcome.unit!r} as {nutrient_def.unit!r}",
        )
    return NutrientAmount(converted, nutrient_def.unit), None


def _build_composition(
    food: FoodRecord, dataset: Dataset, nutrients: Iterable[str]
) -> tuple[Composition | None, dict[str, Resolved | Unresolved]]:
    """Build a Composition from a FoodRecord for the requested nutrients.

    Returns (Composition, {nutrient: outcome}) where outcomes contains any
    unresolved nutrients.
    """
    per_100g: dict[str, NutrientAmount] = {}
    outcomes: dict[str, Resolved | Unresolved] = {}

    for nutrient_id in nutrients:
        amount, outcome = _get_nutrient_per_100g(food, nutrient_id, dataset)
        if outcome is not None:
            outcomes[nutrient_id] = outcome
        elif amount is not None:
            per_100g[nutrient_id] = amount

    if not per_100g and outcomes:
        # All nutrients failed
        return None, outcomes

    composition = Composition(
        food_id=food.key,
        description=food.description,
        basis=BASIS_UNSPECIFIED,
        per_100g=per_100g,
        provenance=dataset.provenance_for(
            food.provider,
            food.source_id,
            "measured",
            0.95,  # Default confidence for composition records
            LINE_QUERY_VERSION,
        ),
    )
    return composition, outcomes


def _scale_nutrient(
    per_100g_value: float,
    grams: float,
    composition_prov: Provenance,
    grams_prov: Provenance,
    nutrient_id: str,
) -> Resolved:
    """Scale a per-100g nutrient value to the actual grams consumed.

    The method is the weakest link (capped at calculated), and confidence
    is the product of inputs.
    """
    from .nutrition import _clamp01, _round

    # Method is the weakest link, capped at calculated
    method = weakest_method(
        "calculated", composition_prov.method, grams_prov.method
    )

    # Confidence is the product of inputs (independent chain)
    confidence = _clamp01(composition_prov.confidence * grams_prov.confidence)

    # Value calculation
    value = (grams / 100.0) * per_100g_value

    # Build provenance
    # Map USDA nutrient IDs to foodcore IDs
    normalized_id = _normalize_nutrient_id(nutrient_id)
    nutrient_def = NUTRIENTS.get(normalized_id)
    unit = nutrient_def.unit if nutrient_def else "g"

    return Resolved(
        value=_round(value),
        unit=unit,
        provenance=Provenance(
            source="internal",
            source_id=f"calc({composition_prov.source}:{composition_prov.source_id}+{grams_prov.source_id})",
            retrieved=min(composition_prov.retrieved, grams_prov.retrieved),
            method=method,
            version=f"{composition_prov.version}+{grams_prov.version}+{ALGORITHM_VERSION}",
            confidence=_round(confidence),
            license=composition_prov.license,
        ),
    )


def line_query(
    text: str,
    dataset: Dataset,
    nutrients: Iterable[str] | None = None,
) -> dict[str, Resolved | Unresolved]:
    """Query nutrition for an ingredient line.

    Args:
        text: An ingredient line like "2 cups chopped canned tomatoes"
        dataset: The foodcore Dataset to use for lookups
        nutrients: Which nutrients to return. If None, returns all nutrients
                   the food's composition record contains.

    Returns:
        A dict mapping nutrient_id to Resolved or Unresolved outcome.
        Each outcome includes the value, unit, and provenance (or reason/detail).

    The function follows foodcore's core rules:
    - Missing is not zero: an absent nutrient returns Unresolved, not 0
    - Weakest-link provenance: the method is the weakest of all steps
    - Confidence product: independent error probabilities compound
    """
    if not text or not text.strip():
        return {
            "error": Unresolved(
                reason="empty_input",
                detail="ingredient line cannot be empty",
            )
        }

    if dataset is None:
        return {
            "error": Unresolved(
                reason="no_dataset",
                detail="no reference dataset is loaded; load one to resolve foods",
            )
        }

    # Parse the line to extract amount, unit, and food text
    from .convert import parse_quantity

    parsed = parse_quantity(text)
    if parsed.amount is None:
        return {
            "error": Unresolved(
                reason="no_quantity",
                detail=f"no leading quantity found in {text!r}",
            )
        }

    # Resolve the food
    food, food_error = _resolve_food(parsed.food_text, dataset)
    if isinstance(food_error, Unresolved):
        return {"error": food_error}

    # Get grams for the amount
    grams, grams_error = _get_grams(text, dataset)
    if isinstance(grams_error, Unresolved):
        return {"error": grams_error}

    # Determine which nutrients to query
    if nutrients is None:
        # Use all nutrients from the food's record
        nutrient_ids_list = list(food.nutrients.keys())
    else:
        nutrient_ids_list = list(nutrients)

    if not nutrient_ids_list:
        return {}

    # Build composition and get per-nutrient outcomes
    composition, nutrient_outcomes = _build_composition(food, dataset, nutrient_ids_list)

    # If composition couldn't be built, return the error
    if composition is None and nutrient_outcomes:
        # Return the first error as "error", others as individual nutrients
        result: dict[str, Resolved | Unresolved] = {}
        error_keys = list(nutrient_outcomes.keys())
        if error_keys:
            result["error"] = nutrient_outcomes[error_keys[0]]
            # Also include other nutrients as unresolved
            for key in error_keys[1:]:
                result[key] = nutrient_outcomes[key]
        return result

    # Calculate scaled values for each nutrient
    result: dict[str, Resolved | Unresolved] = {}

    # First, add any nutrients that failed during composition building
    for nutrient_id, outcome in nutrient_outcomes.items():
        result[nutrient_id] = outcome

    # Then calculate values for nutrients that succeeded
    if composition is not None:
        grams_prov = grams.provenance if isinstance(grams, Resolved) else composition.provenance

        for nutrient_id in nutrient_ids_list:
            if nutrient_id in result:
                continue  # Already have an outcome (either resolved or unresolved)

            amount = composition.per_100g.get(nutrient_id)
            if amount is None:
                # Nutrient not reported by this food
                result[nutrient_id] = Unresolved(
                    reason="nutrient_not_reported",
                    detail=f"{food.description} does not report {nutrient_id}",
                )
                continue

            # Scale from per-100g to actual grams
            scaled = _scale_nutrient(
                amount.amount,
                grams,
                composition.provenance,
                grams_prov,
                nutrient_id,
            )
            result[nutrient_id] = scaled

    return result


__all__ = ["line_query"]
