"""The %Daily Value engine for nutrition panels.

This module provides a shared reference for FDA Daily Values so both
host apps (myMeal recipe panels, Edibl nutrition displays) can turn
absolute nutrient amounts into FDA-reference percentages from one
shared, provenance-carrying table.

Usage:
    from foodcore import dv

    # Single nutrient
    result = dv.percent("sodium", 575)
    # Resolved(25.0, "%", provenance=Provenance(...))

    # Multiple nutrients
    panel = dv.panel({"sodium": 575, "vitamin_c": 100})
    # {"sodium": Resolved(25.0, "%", ...), "vitamin_c": Resolved(111.11, "%", ...)}

Public API:
    percent(nutrient_id, amount, *, version=rule_version("dv")) -> Resolved | Unresolved
    panel(mapping, *, version=rule_version("dv")) -> dict[str, Resolved | Unresolved]
"""

from __future__ import annotations

from typing import Mapping

from .provenance import Resolved, Unresolved
from .rules.dv_v1 import (
    DailyValue,
    NO_DV_IDS,
    _DV_TABLE,
    panel as _panel,
    percent as _percent,
)

__all__ = ["percent", "panel", "DailyValue", "NO_DV_IDS", "_DV_TABLE"]


def percent(nutrient_id: str, amount: float, *, version: str | None = None) -> Resolved | Unresolved:
    """Compute % Daily Value for a nutrient amount.

    Args:
        nutrient_id: The nutrient identifier (e.g., "sodium", "vitamin_c").
        amount: The absolute amount of the nutrient.
        version: Rule version (optional; defaults to dv/1).

    Returns:
        Resolved(percent, "%") if a DV exists for this nutrient.
        Unresolved with reason "no_daily_value" if FDA establishes no DV
            (protein, trans_fat, sugar).
        Unresolved with reason "unknown_nutrient" if the nutrient id is unknown.

    Examples:
        >>> percent("sodium", 575)
        Resolved(25.0, "%", ...)
        >>> percent("protein", 30)
        Unresolved("no_daily_value", ...)
        >>> percent("unknown_nutrient", 100)
        Unresolved("unknown_nutrient", ...)
    """
    if version is None:
        from . import rule_version
        version = rule_version("dv")
    return _percent(nutrient_id, amount, version=version)


def panel(mapping: Mapping[str, float], *, version: str | None = None) -> dict[str, Resolved | Unresolved]:
    """Compute % Daily Value for multiple nutrients.

    Args:
        mapping: {nutrient_id: amount} pairs.
        version: Rule version (optional; defaults to dv/1).

    Returns:
        {nutrient_id: Outcome} with one entry per input key.

    Examples:
        >>> panel({"sodium": 575, "vitamin_c": 100})
        {"sodium": Resolved(25.0, "%", ...), "vitamin_c": Resolved(111.11, "%", ...)}
    """
    if version is None:
        from . import rule_version
        version = rule_version("dv")
    return _panel(mapping, version=version)
