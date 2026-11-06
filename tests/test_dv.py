"""Tests for the %Daily Value engine.

The DV table is a closed reference (FDA 21 CFR 101.9) so tests use
hardcoded values rather than deriving them from the table.
"""
import pytest

from foodcore import dv, rule_version
from foodcore.provenance import Resolved, Unresolved


# Spot-check values from FDA DV table (2000 kcal reference)
DV_TESTS = [
    # Sodium: DV = 2300 mg, so 575 mg = 25%
    ("sodium", 575.0, 25.0),
    ("sodium", 2300.0, 100.0),
    ("sodium", 1150.0, 50.0),
    # Vitamin C: DV = 90 mg
    ("vitamin_c", 90.0, 100.0),
    ("vitamin_c", 45.0, 50.0),
    # Carbs: DV = 275 g
    ("carbs", 275.0, 100.0),
    ("carbs", 137.5, 50.0),
    # Calories: DV = 2000 kcal
    ("calories", 2000.0, 100.0),
    ("calories", 1000.0, 50.0),
    # Potassium: DV = 4700 mg
    ("potassium", 4700.0, 100.0),
    ("potassium", 2350.0, 50.0),
]


@pytest.mark.parametrize(("nutrient_id", "amount", "expected_pct"), DV_TESTS)
def test_percent_resolved(nutrient_id, amount, expected_pct):
    """Resolved nutrients return a percentage."""
    result = dv.percent(nutrient_id, amount)
    assert isinstance(result, Resolved), f"Expected Resolved, got {type(result)}"
    assert result.unit == "%"
    assert result.value == pytest.approx(expected_pct, rel=0.01)
    # Check provenance
    assert result.provenance.source == "internal"
    assert result.provenance.method == "declared"
    assert result.provenance.version == rule_version("dv")


def test_percent_no_daily_value_protein():
    """Protein has no FDA DV."""
    result = dv.percent("protein", 30.0)
    assert isinstance(result, Unresolved)
    assert result.reason == "no_daily_value"
    assert "protein" in result.detail


def test_percent_no_daily_value_trans_fat():
    """Trans fat has no FDA DV."""
    result = dv.percent("trans_fat", 1.0)
    assert isinstance(result, Unresolved)
    assert result.reason == "no_daily_value"
    assert "trans_fat" in result.detail


def test_percent_no_daily_value_sugar():
    """Sugar has no FDA DV."""
    result = dv.percent("sugar", 10.0)
    assert isinstance(result, Unresolved)
    assert result.reason == "no_daily_value"
    assert "sugar" in result.detail


def test_percent_unknown_nutrient():
    """Unknown nutrient ids return unknown_nutrient."""
    result = dv.percent("unknown_nutrient", 100.0)
    assert isinstance(result, Unresolved)
    assert result.reason == "unknown_nutrient"
    assert "unknown_nutrient" in result.detail


def test_percent_custom_version():
    """Custom version is passed through to provenance."""
    result = dv.percent("sodium", 575.0, version="custom/99")
    assert result.provenance.version == "custom/99"


def test_panel_single_nutrient():
    """panel() works with one nutrient."""
    result = dv.panel({"sodium": 575.0})
    assert isinstance(result, dict)
    assert "sodium" in result
    assert isinstance(result["sodium"], Resolved)
    assert result["sodium"].value == 25.0


def test_panel_multiple_nutrients():
    """panel() returns one outcome per input key."""
    mapping = {
        "sodium": 575.0,
        "vitamin_c": 90.0,
        "protein": 30.0,
    }
    result = dv.panel(mapping)
    assert len(result) == 3
    assert isinstance(result["sodium"], Resolved)
    assert result["sodium"].value == 25.0
    assert isinstance(result["vitamin_c"], Resolved)
    assert result["vitamin_c"].value == 100.0
    assert isinstance(result["protein"], Unresolved)
    assert result["protein"].reason == "no_daily_value"


def test_panel_unknown_nutrient():
    """panel() handles unknown nutrients."""
    result = dv.panel({"unknown": 100.0})
    assert isinstance(result["unknown"], Unresolved)
    assert result["unknown"].reason == "unknown_nutrient"


def test_panel_mixed():
    """panel() returns Resolved and Unresolved in the same dict."""
    result = dv.panel({
        "sodium": 575.0,
        "protein": 30.0,
        "vitamin_c": 90.0,
    })
    assert isinstance(result["sodium"], Resolved)
    assert isinstance(result["protein"], Unresolved)
    assert isinstance(result["vitamin_c"], Resolved)


def test_lazy_import():
    """dv is available via lazy import."""
    import foodcore
    assert hasattr(foodcore, "dv")
    assert hasattr(foodcore.dv, "percent")
    assert hasattr(foodcore.dv, "panel")


def test_percent_zero_amount():
    """Zero amount returns 0% (not an error)."""
    result = dv.percent("sodium", 0.0)
    assert isinstance(result, Resolved)
    assert result.value == 0.0


def test_percent_negative_amount():
    """Negative amounts are allowed (mathematically)."""
    result = dv.percent("sodium", -100.0)
    assert isinstance(result, Resolved)
    assert result.value == pytest.approx(-4.35, rel=0.01)


def test_panel_empty():
    """panel() with empty dict returns empty dict."""
    result = dv.panel({})
    assert result == {}


def test_dv_module_attributes():
    """Module exposes expected attributes."""
    assert hasattr(dv, "percent")
    assert hasattr(dv, "panel")
    assert hasattr(dv, "NO_DV_IDS")
    assert hasattr(dv, "_DV_TABLE")
