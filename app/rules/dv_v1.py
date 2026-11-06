"""FDA Daily Values for adults and children ≥4 years (2016/2020 21 CFR 101.9).

The table maps nutrient ids (from nutrition.NUTRIENTS) to their reference
Daily Values in the unit the registry uses. A missing key means FDA establishes
no Daily Value for that nutrient (protein, trans_fat, sugar).

Source: 21 CFR 101.9 -- Nutrition labeling of food
Baseline: 2000 kcal diet; DVs are percentages of that reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

# Local imports (deferred in percent() to avoid circular dependency)
from ..provenance import Provenance, Resolved, Unresolved

# --------------------------------------------------------------------------
# FDA Daily Values for adults and children ≥4 years
# --------------------------------------------------------------------------
# Values are in the unit used by nutrition.NUTRIENTS (not converted).
# A nutrient id not present here means FDA establishes no DV.
# --------------------------------------------------------------------------
_DV_TABLE: Mapping[str, float] = {
    # Energy
    "calories": 2000.0,
    # Macros
    "fat": 78.0,              # g
    "saturated_fat": 20.0,    # g
    "cholesterol": 300.0,     # mg
    "sodium": 2300.0,         # mg
    "carbs": 275.0,           # g
    "fiber": 28.0,            # g
    # Micronutrients
    "calcium": 1300.0,        # mg
    "iron": 18.0,             # mg
    "potassium": 4700.0,      # mg
    "magnesium": 420.0,       # mg
    "zinc": 11.0,             # mg
    "vitamin_a_rae": 900.0,   # µg RAE
    "vitamin_c": 90.0,        # mg
    "vitamin_d": 20.0,        # µg
    "vitamin_e": 15.0,        # mg
    "vitamin_k": 120.0,       # µg
    "thiamin": 1.2,           # mg
    "riboflavin": 1.3,        # mg
    "niacin": 16.0,           # mg
    "vitamin_b6": 1.7,        # mg
    "folate": 400.0,          # µg DFE
    "vitamin_b12": 2.4,       # µg
    # Additional minerals
    "selenium": 55.0,         # µg
    "iodine": 150.0,          # µg
    "manganese": 2.3,         # mg
}


#: Nutrient ids that FDA explicitly states have no Daily Value.
#: These return Unresolved(no_daily_value) rather than a percentage.
NO_DV_IDS = frozenset({
    "protein",
    "trans_fat",
    "sugar",
})


#: Rule version for this DV table.
VERSION = "dv/1"


@dataclass(frozen=True)
class DailyValue:
    """A single nutrient's Daily Value with its provenance."""
    amount: float
    unit: str
    source: str = "internal"
    source_id: str = "fda-21-cfr-101-9"
    retrieved: str = "2020-01-01"  # FDA 2020 rule effective date
    method: str = "declared"
    version: str = VERSION
    license: str = "internal"


def get_daily_value(nutrient_id: str) -> DailyValue | None:
    """Return the DV for a nutrient id, or None if FDA establishes no DV."""
    if nutrient_id in NO_DV_IDS:
        return None
    if nutrient_id not in _DV_TABLE:
        return None
    from foodcore.nutrition import NUTRIENTS
    unit = NUTRIENTS[nutrient_id].unit if nutrient_id in NUTRIENTS else "unit"
    return DailyValue(
        amount=_DV_TABLE[nutrient_id],
        unit=unit,
    )


def percent(nutrient_id: str, amount: float, *, version: str | None = None) -> Resolved | Unresolved:
    """Compute % Daily Value for a nutrient amount.

    Args:
        nutrient_id: The nutrient identifier (e.g., "sodium", "vitamin_c").
        amount: The absolute amount of the nutrient.
        version: Rule version (optional; defaults to dv/1).

    Returns:
        Resolved(percent, "%") if a DV exists for this nutrient.
        Unresolved with reason "no_daily_value" if FDA establishes no DV.
        Unresolved with reason "unknown_nutrient" if the nutrient id is unknown.

    Examples:
        >>> percent("sodium", 575)
        Resolved(25.0, "%", ...)
        >>> percent("protein", 30)
        Unresolved("no_daily_value", ...)
    """

    if nutrient_id not in _DV_TABLE and nutrient_id not in NO_DV_IDS:
        return Unresolved(
            reason="unknown_nutrient",
            detail=f"no Daily Value defined for nutrient {nutrient_id!r}",
        )

    if nutrient_id in NO_DV_IDS:
        return Unresolved(
            reason="no_daily_value",
            detail=f"FDA establishes no Daily Value for {nutrient_id}",
        )

    dv = get_daily_value(nutrient_id)
    if dv is None:
        return Unresolved(
            reason="unknown_nutrient",
            detail=f"no Daily Value defined for nutrient {nutrient_id!r}",
        )

    pct = (amount / dv.amount) * 100.0

    return Resolved(
        value=round(pct, 2),
        unit="%",
        provenance=Provenance(
            source=dv.source,
            source_id=dv.source_id,
            retrieved=dv.retrieved,
            method=dv.method,
            version=dv.version if version is None else version,
            confidence=1.0,
            license=dv.license,
        ),
    )


def panel(mapping: Mapping[str, float], *, version: str | None = None) -> dict[str, Resolved | Unresolved]:
    """Compute % Daily Value for multiple nutrients.

    Args:
        mapping: {nutrient_id: amount} pairs.
        version: Rule version (optional; defaults to dv/1).

    Returns:
        {nutrient_id: Outcome} with one entry per input key.
    """
    return {
        nid: percent(nid, amount, version=version)
        for nid, amount in mapping.items()
    }
