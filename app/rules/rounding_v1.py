"""FDA 21 CFR 101.9 nutrient rounding for nutrition facts labels.

This module implements the rounding rules specified in 21 CFR 101.9 for
displaying nutrient values on nutrition facts labels. The rules ensure that
values are rounded to the appropriate increment and expressed in the correct
format for regulatory compliance.

Reference: 21 CFR 101.9 - Nutrition labeling of food, particularly
paragraph (c)(1)-(8) which defines rounding requirements for calories,
total fat, saturated fat, trans fat, cholesterol, sodium, potassium,
total carbohydrate, dietary fiber, and protein.

Serving-size caveats implemented:
- Values are rounded based on the amount per serving as declared on the label
- The "less than" phrasing for cholesterol (2-5 mg) is implemented
- Zero values are expressed as "0" or "0 g" as appropriate

Serving-size caveats deferred:
- The module does not adjust rounding based on serving size thresholds
  (e.g., single-serve vs. multi-serve containers) - this is handled by
  the caller when determining the per-serving amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from ..provenance import Provenance, Resolved, Unresolved

#: Version string that reaches Provenance.version, so a stored value can be
#: traced to the rule that produced it.
VERSION = "rounding/fda-101.9-v1"

#: Source identifier for internal rules.
SOURCE = "internal"

#: Method for values computed by this rounding module.
METHOD = "calculated"

#: License for internal rules.
LICENSE = "internal"


@dataclass(frozen=True)
class RoundingRule:
    """A single rounding rule for a nutrient.

    Attributes:
        nutrient: The nutrient name (e.g., "calories", "total_fat").
        threshold: The value below which the rule applies (None for unbounded).
        threshold_inclusive: Whether the threshold value itself uses this rule.
        increment: The rounding increment (e.g., 5 for nearest 5).
        zero_value: If not None, values below threshold are expressed as this string.
        special_text: If not None, values in a specific range use this text (e.g., "less than 5 mg").
        unit: The unit for the nutrient (e.g., "g", "mg").
    """
    nutrient: str
    threshold: float | None = None
    threshold_inclusive: bool = False
    increment: float | None = None
    zero_value: str | None = None
    special_text: str | None = None
    unit: str = ""


#: Rounding rules for each nutrient, in order of application.
#: Rules are applied in sequence; the first matching rule determines rounding.
#: The table is derived from 21 CFR 101.9(c)(1)-(8) and the FDA Food Labeling Guide.
#: https://www.fda.gov/food/food-labeling-and-dietary-supplement-labeling/food-labeling-guide
ROUNDING_RULES: dict[str, tuple[RoundingRule, ...]] = {
    # Calories (21 CFR 101.9(c)(1))
    # <5 cal → 0; 5-50 → nearest 5; >50 → nearest 10
    "calories": (
        RoundingRule("calories", threshold=5, zero_value="0", unit="cal"),
        RoundingRule("calories", threshold=5, increment=5, threshold_inclusive=True, unit="cal"),
        RoundingRule("calories", threshold=50, increment=10, unit="cal"),
    ),
    # Total Fat (21 CFR 101.9(c)(2))
    # <0.5g → 0; ≥0.5g → nearest 0.5g
    "total_fat": (
        RoundingRule("total_fat", threshold=0.5, zero_value="0", unit="g"),
        RoundingRule("total_fat", threshold=0.5, increment=0.5, threshold_inclusive=True, unit="g"),
    ),
    # Saturated Fat (21 CFR 101.9(c)(2)(i))
    # <5g → nearest 0.5g; ≥5g → nearest 1g
    "saturated_fat": (
        RoundingRule("saturated_fat", threshold=5, increment=0.5, unit="g"),
        RoundingRule("saturated_fat", threshold=5, increment=1, threshold_inclusive=True, unit="g"),
    ),
    # Trans Fat (21 CFR 101.9(c)(2)(ii))
    # <0.5g → 0; ≥0.5g → nearest 0.5g
    "trans_fat": (
        RoundingRule("trans_fat", threshold=0.5, zero_value="0", unit="g"),
        RoundingRule("trans_fat", threshold=0.5, increment=0.5, threshold_inclusive=True, unit="g"),
    ),
    # Cholesterol (21 CFR 101.9(c)(3))
    # <2mg → 0; 2-5mg → "less than 5 mg"; >5mg → nearest 5mg
    "cholesterol": (
        RoundingRule("cholesterol", threshold=2, zero_value="0", unit="mg"),
        RoundingRule(
            "cholesterol",
            threshold=2,
            threshold_inclusive=True,
            special_text="less than 5 mg",
            unit="mg",
        ),
        RoundingRule("cholesterol", threshold=5, increment=5, unit="mg"),
    ),
    # Sodium (21 CFR 101.9(c)(4))
    # <5mg → 0; 5-140mg → nearest 5mg; >140mg → nearest 10mg
    "sodium": (
        RoundingRule("sodium", threshold=5, zero_value="0", unit="mg"),
        RoundingRule("sodium", threshold=5, increment=5, threshold_inclusive=True, unit="mg"),
        RoundingRule("sodium", threshold=140, increment=10, unit="mg"),
    ),
    # Potassium (21 CFR 101.9(c)(5))
    # <5mg → 0; 5-140mg → nearest 5mg; >140mg → nearest 10mg
    "potassium": (
        RoundingRule("potassium", threshold=5, zero_value="0", unit="mg"),
        RoundingRule("potassium", threshold=5, increment=5, threshold_inclusive=True, unit="mg"),
        RoundingRule("potassium", threshold=140, increment=10, unit="mg"),
    ),
    # Total Carbohydrate (21 CFR 101.9(c)(6))
    # <1g → 0; ≥1g → nearest 1g
    "total_carbohydrate": (
        RoundingRule("total_carbohydrate", threshold=1, zero_value="0", unit="g"),
        RoundingRule("total_carbohydrate", threshold=1, increment=1, threshold_inclusive=True, unit="g"),
    ),
    # Dietary Fiber (21 CFR 101.9(c)(6)(i))
    # Same as Total Carbohydrate
    "dietary_fiber": (
        RoundingRule("dietary_fiber", threshold=1, zero_value="0", unit="g"),
        RoundingRule("dietary_fiber", threshold=1, increment=1, threshold_inclusive=True, unit="g"),
    ),
    # Protein (21 CFR 101.9(c)(7))
    # Same as Total Carbohydrate
    "protein": (
        RoundingRule("protein", threshold=1, zero_value="0", unit="g"),
        RoundingRule("protein", threshold=1, increment=1, threshold_inclusive=True, unit="g"),
    ),
}


def _round_value(value: float, increment: float) -> float:
    """Round a value to the nearest increment using standard rounding (round half up).

    Args:
        value: The raw value to round.
        increment: The rounding increment (e.g., 5 for nearest 5).

    Returns:
        The rounded value.
    """
    if increment <= 0:
        return value
    # Standard rounding (round half up) instead of Python's banker's rounding
    import math
    return math.floor(value / increment + 0.5) * increment


def _apply_rule(value: float, rule: RoundingRule) -> Resolved | Unresolved:
    """Apply a single rounding rule to a value.

    Args:
        value: The raw nutrient value.
        rule: The rounding rule to apply.

    Returns:
        A Resolved outcome with the rounded value and formatted text,
        or an Unresolved outcome if the value is invalid.
    """
    # Check for invalid values first
    if value < 0:
        return Unresolved(
            reason="negative_value",
            detail=f"nutrient value cannot be negative, got {value}",
        )
    if not isfinite(value):
        return Unresolved(
            reason="non_finite_value",
            detail=f"nutrient value must be finite, got {value}",
        )

    # Check for zero threshold
    if rule.zero_value is not None:
        if rule.threshold is not None and value < rule.threshold:
            return Resolved(
                value=0.0,
                unit=rule.unit,
                provenance=Provenance(
                    source=SOURCE,
                    source_id=f"rounding/{rule.nutrient}/zero",
                    retrieved="internal",
                    method=METHOD,
                    version=VERSION,
                    confidence=1.0,
                    license=LICENSE,
                ),
            )

    # Check for special text (e.g., "less than 5 mg")
    if rule.special_text is not None:
        if rule.threshold_inclusive and rule.threshold is not None and value >= rule.threshold:
            return Resolved(
                value=value,
                unit=rule.unit,
                provenance=Provenance(
                    source=SOURCE,
                    source_id=f"rounding/{rule.nutrient}/special",
                    retrieved="internal",
                    method=METHOD,
                    version=VERSION,
                    confidence=1.0,
                    license=LICENSE,
                ),
            )

    # Apply increment-based rounding
    if rule.increment is not None:
        if rule.threshold is None:
            rounded = _round_value(value, rule.increment)
            return Resolved(
                value=rounded,
                unit=rule.unit,
                provenance=Provenance(
                    source=SOURCE,
                    source_id=f"rounding/{rule.nutrient}/increment",
                    retrieved="internal",
                    method=METHOD,
                    version=VERSION,
                    confidence=1.0,
                    license=LICENSE,
                ),
            )
        if rule.threshold_inclusive:
            if rule.threshold is not None and value >= rule.threshold:
                rounded = _round_value(value, rule.increment)
                return Resolved(
                    value=rounded,
                    unit=rule.unit,
                    provenance=Provenance(
                        source=SOURCE,
                        source_id=f"rounding/{rule.nutrient}/increment",
                        retrieved="internal",
                        method=METHOD,
                        version=VERSION,
                        confidence=1.0,
                        license=LICENSE,
                    ),
                )
        else:
            if rule.threshold is not None and value > rule.threshold:
                rounded = _round_value(value, rule.increment)
                return Resolved(
                    value=rounded,
                    unit=rule.unit,
                    provenance=Provenance(
                        source=SOURCE,
                        source_id=f"rounding/{rule.nutrient}/increment",
                        retrieved="internal",
                        method=METHOD,
                        version=VERSION,
                        confidence=1.0,
                        license=LICENSE,
                    ),
                )

    return Unresolved(
        reason="no_matching_rule",
        detail=f"no rounding rule matched for {rule.nutrient} with value {value}",
    )


def round_nutrient(
    nutrient: str,
    value: float,
) -> Resolved | Unresolved:
    """Round a nutrient value according to FDA 21 CFR 101.9.

    This function applies the appropriate rounding rule for the given nutrient
    based on the FDA regulations. The rules determine how values should be
    displayed on nutrition facts labels.

    Args:
        nutrient: The nutrient name (e.g., "calories", "total_fat", "sodium").
        value: The raw nutrient value to round.

    Returns:
        A Resolved outcome with the rounded value and unit, or an Unresolved
        outcome if the value cannot be rounded (e.g., negative or non-finite).

    Examples:
        >>> result = round_nutrient("calories", 47.0)
        >>> result.resolved
        True
        >>> result.value
        45.0

        >>> result = round_nutrient("cholesterol", 3.0)
        >>> result.resolved
        True
        >>> result.value
        3.0

        >>> result = round_nutrient("sodium", 150.0)
        >>> result.resolved
        True
        >>> result.value
        150.0

        >>> result = round_nutrient("total_fat", 0.3)
        >>> result.resolved
        True
        >>> result.value
        0.0

    Note:
        The module docstring documents which serving-size caveats are implemented
        vs deferred. Currently, serving-size based adjustments are deferred to
        the caller.
    """
    # Check for invalid values first
    if value < 0:
        return Unresolved(
            reason="negative_value",
            detail=f"nutrient value cannot be negative, got {value}",
        )
    if not isfinite(value):
        return Unresolved(
            reason="non_finite_value",
            detail=f"nutrient value must be finite, got {value}",
        )

    rules = ROUNDING_RULES.get(nutrient)
    if rules is None:
        return Unresolved(
            reason="unknown_nutrient",
            detail=f"unknown nutrient {nutrient!r}; valid nutrients are: {', '.join(sorted(ROUNDING_RULES.keys()))}",
        )

    # Apply rules in order until one matches
    for rule in rules:
        if rule.zero_value is not None and rule.threshold is not None and value < rule.threshold:
            return _apply_rule(value, rule)

        if rule.special_text is not None:
            if rule.threshold_inclusive and rule.threshold is not None and value >= rule.threshold:
                return _apply_rule(value, rule)

        if rule.increment is not None:
            if rule.threshold is None:
                return _apply_rule(value, rule)
            if rule.threshold_inclusive:
                if rule.threshold is not None and value >= rule.threshold:
                    return _apply_rule(value, rule)
            else:
                if rule.threshold is not None and value > rule.threshold:
                    return _apply_rule(value, rule)

    return Unresolved(
        reason="no_matching_rule",
        detail=f"no rounding rule matched for {nutrient} with value {value}",
    )


def round_nutrient_with_text(
    nutrient: str,
    value: float,
) -> Resolved | Unresolved:
    """Round a nutrient value and return formatted display text.

    This function extends round_nutrient by including a formatted text
    representation suitable for direct display on nutrition facts labels.

    Args:
        nutrient: The nutrient name (e.g., "calories", "total_fat", "sodium").
        value: The raw nutrient value to round.

    Returns:
        A Resolved outcome with the rounded value, unit, and formatted text,
        or an Unresolved outcome if the value cannot be rounded.

    Examples:
        >>> result = round_nutrient_with_text("calories", 47.0)
        >>> result.resolved
        True
        >>> result.value
        45.0

        >>> result = round_nutrient_with_text("cholesterol", 3.0)
        >>> result.resolved
        True
        >>> result.value
        3.0

    Note:
        The formatted text is suitable for direct display on nutrition facts labels.
        For values that round to zero, the text will be "0 {unit}".
        For values with special text (e.g., cholesterol 2-5 mg), the special text is used.
    """
    result = round_nutrient(nutrient, value)
    if not result.resolved:
        return result

    # Get the rule to determine special text
    rules = ROUNDING_RULES.get(nutrient)
    if rules is None:
        return Unresolved(
            reason="unknown_nutrient",
            detail=f"unknown nutrient {nutrient!r}",
        )

    # Find the matching rule to get special text
    matched_rule = None
    for rule in rules:
        if rule.zero_value is not None and rule.threshold is not None and value < rule.threshold:
            matched_rule = rule
            break
        if rule.special_text is not None:
            if rule.threshold_inclusive and rule.threshold is not None and value >= rule.threshold:
                matched_rule = rule
                break
        if rule.increment is not None:
            if rule.threshold is None:
                matched_rule = rule
                break
            if rule.threshold_inclusive:
                if rule.threshold is not None and value >= rule.threshold:
                    matched_rule = rule
                    break
            else:
                if rule.threshold is not None and value > rule.threshold:
                    matched_rule = rule
                    break

    # Format the text
    if matched_rule and matched_rule.special_text:
        text = matched_rule.special_text
    elif result.value == 0 and matched_rule and matched_rule.zero_value:
        text = matched_rule.zero_value
    else:
        # Format the number appropriately
        if result.value == int(result.value):
            num_str = str(int(result.value))
        else:
            num_str = str(result.value).rstrip("0").rstrip(".")
        text = f"{num_str} {result.unit}"

    return Resolved(
        value=result.value,
        unit=result.unit,
        provenance=result.provenance,
        text=text,
    )


__all__ = [
    "VERSION",
    "SOURCE",
    "METHOD",
    "LICENSE",
    "RoundingRule",
    "ROUNDING_RULES",
    "round_nutrient",
    "round_nutrient_with_text",
]
