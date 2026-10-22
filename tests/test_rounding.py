"""Tests for FDA 21 CFR 101.9 nutrient rounding.

These tests verify the rounding rules specified in 21 CFR 101.9 for
nutrition facts labels. The tests cover boundary cases directly from
the regulation.

Reference: 21 CFR 101.9 - Nutrition labeling of food
"""

from foodcore.rules.rounding_v1 import (
    VERSION,
    round_nutrient,
    round_nutrient_with_text,
)


# --- Calories (21 CFR 101.9(c)(1)) ---
# <5 cal → 0; 5-50 → nearest 5; >50 → nearest 10


def test_calories_boundary_below_5():
    """Values below 5 cal round to 0."""
    result = round_nutrient("calories", 4.0)
    assert result.resolved
    assert result.value == 0.0
    assert result.unit == "cal"


def test_calories_boundary_at_5():
    """5 cal rounds to nearest 5 (i.e., 5)."""
    result = round_nutrient("calories", 5.0)
    assert result.resolved
    assert result.value == 5.0
    assert result.unit == "cal"


def test_calories_boundary_49():
    """49 cal rounds to nearest 5 (i.e., 50)."""
    result = round_nutrient("calories", 49.0)
    assert result.resolved
    assert result.value == 50.0
    assert result.unit == "cal"


def test_calories_boundary_at_50():
    """50 cal rounds to nearest 5 (i.e., 50)."""
    result = round_nutrient("calories", 50.0)
    assert result.resolved
    assert result.value == 50.0
    assert result.unit == "cal"


def test_calories_boundary_51():
    """51 cal rounds to nearest 10 (i.e., 50)."""
    result = round_nutrient("calories", 51.0)
    assert result.resolved
    assert result.value == 50.0
    assert result.unit == "cal"


def test_calories_boundary_54():
    """54 cal rounds to nearest 10 (i.e., 50)."""
    result = round_nutrient("calories", 54.0)
    assert result.resolved
    assert result.value == 50.0
    assert result.unit == "cal"


def test_calories_boundary_55():
    """55 cal rounds to nearest 10 (i.e., 60)."""
    result = round_nutrient("calories", 55.0)
    assert result.resolved
    assert result.value == 60.0
    assert result.unit == "cal"


def test_calories_boundary_96():
    """96 cal rounds to nearest 10 (i.e., 100)."""
    result = round_nutrient("calories", 96.0)
    assert result.resolved
    assert result.value == 100.0
    assert result.unit == "cal"


# --- Total Fat (21 CFR 101.9(c)(2)) ---
# <0.5g → 0; ≥0.5g → nearest 0.5g


def test_total_fat_boundary_below_0_5():
    """Values below 0.5g round to 0."""
    result = round_nutrient("total_fat", 0.4)
    assert result.resolved
    assert result.value == 0.0
    assert result.unit == "g"


def test_total_fat_boundary_at_0_5():
    """0.5g rounds to nearest 0.5 (i.e., 0.5)."""
    result = round_nutrient("total_fat", 0.5)
    assert result.resolved
    assert result.value == 0.5
    assert result.unit == "g"


def test_total_fat_boundary_0_7():
    """0.7g rounds to nearest 0.5 (i.e., 0.5)."""
    result = round_nutrient("total_fat", 0.7)
    assert result.resolved
    assert result.value == 0.5
    assert result.unit == "g"


def test_total_fat_boundary_0_8():
    """0.8g rounds to nearest 0.5 (i.e., 1.0)."""
    result = round_nutrient("total_fat", 0.8)
    assert result.resolved
    assert result.value == 1.0
    assert result.unit == "g"


def test_total_fat_boundary_1_2():
    """1.2g rounds to nearest 0.5 (i.e., 1.0)."""
    result = round_nutrient("total_fat", 1.2)
    assert result.resolved
    assert result.value == 1.0
    assert result.unit == "g"


def test_total_fat_boundary_1_3():
    """1.3g rounds to nearest 0.5 (i.e., 1.5)."""
    result = round_nutrient("total_fat", 1.3)
    assert result.resolved
    assert result.value == 1.5
    assert result.unit == "g"


# --- Saturated Fat (21 CFR 101.9(c)(2)(i)) ---
# <5g → nearest 0.5g; ≥5g → nearest 1g


def test_saturated_fat_boundary_below_5():
    """Values below 5g round to nearest 0.5."""
    result = round_nutrient("saturated_fat", 4.0)
    assert result.resolved
    assert result.value == 4.0
    assert result.unit == "g"


def test_saturated_fat_boundary_4_5():
    """4.5g rounds to nearest 0.5 (i.e., 4.5)."""
    result = round_nutrient("saturated_fat", 4.5)
    assert result.resolved
    assert result.value == 4.5
    assert result.unit == "g"


def test_saturated_fat_boundary_at_5():
    """5g rounds to nearest 1 (i.e., 5)."""
    result = round_nutrient("saturated_fat", 5.0)
    assert result.resolved
    assert result.value == 5.0
    assert result.unit == "g"


def test_saturated_fat_boundary_5_3():
    """5.3g rounds to nearest 1 (i.e., 5)."""
    result = round_nutrient("saturated_fat", 5.3)
    assert result.resolved
    assert result.value == 5.0
    assert result.unit == "g"


def test_saturated_fat_boundary_5_6():
    """5.6g rounds to nearest 1 (i.e., 6)."""
    result = round_nutrient("saturated_fat", 5.6)
    assert result.resolved
    assert result.value == 6.0
    assert result.unit == "g"


# --- Trans Fat (21 CFR 101.9(c)(2)(ii)) ---
# <0.5g → 0; ≥0.5g → nearest 0.5g


def test_trans_fat_boundary_below_0_5():
    """Values below 0.5g round to 0."""
    result = round_nutrient("trans_fat", 0.4)
    assert result.resolved
    assert result.value == 0.0
    assert result.unit == "g"


def test_trans_fat_boundary_at_0_5():
    """0.5g rounds to nearest 0.5 (i.e., 0.5)."""
    result = round_nutrient("trans_fat", 0.5)
    assert result.resolved
    assert result.value == 0.5
    assert result.unit == "g"


# --- Cholesterol (21 CFR 101.9(c)(3)) ---
# <2mg → 0; 2-5mg → "less than 5 mg"; >5mg → nearest 5mg


def test_cholesterol_boundary_below_2():
    """Values below 2mg round to 0."""
    result = round_nutrient("cholesterol", 1.9)
    assert result.resolved
    assert result.value == 0.0
    assert result.unit == "mg"


def test_cholesterol_boundary_at_2():
    """2-5mg is expressed as 'less than 5 mg'."""
    result = round_nutrient("cholesterol", 2.0)
    assert result.resolved
    assert result.value == 2.0
    assert result.unit == "mg"


def test_cholesterol_boundary_3():
    """3mg is expressed as 'less than 5 mg'."""
    result = round_nutrient("cholesterol", 3.0)
    assert result.resolved
    assert result.value == 3.0
    assert result.unit == "mg"


def test_cholesterol_boundary_at_5():
    """5mg rounds to nearest 5 (i.e., 5)."""
    result = round_nutrient("cholesterol", 5.0)
    assert result.resolved
    assert result.value == 5.0
    assert result.unit == "mg"


def test_cholesterol_boundary_6():
    """6mg rounds to nearest 5 (i.e., 5)."""
    result = round_nutrient("cholesterol", 6.0)
    assert result.resolved
    assert result.value == 5.0
    assert result.unit == "mg"


def test_cholesterol_boundary_7():
    """7mg rounds to nearest 5 (i.e., 5)."""
    result = round_nutrient("cholesterol", 7.0)
    assert result.resolved
    assert result.value == 5.0
    assert result.unit == "mg"


def test_cholesterol_boundary_8():
    """8mg rounds to nearest 5 (i.e., 10)."""
    result = round_nutrient("cholesterol", 8.0)
    assert result.resolved
    assert result.value == 10.0
    assert result.unit == "mg"


# --- Sodium (21 CFR 101.9(c)(4)) ---
# <5mg → 0; 5-140mg → nearest 5mg; >140mg → nearest 10mg


def test_sodium_boundary_below_5():
    """Values below 5mg round to 0."""
    result = round_nutrient("sodium", 4.0)
    assert result.resolved
    assert result.value == 0.0
    assert result.unit == "mg"


def test_sodium_boundary_at_5():
    """5mg rounds to nearest 5 (i.e., 5)."""
    result = round_nutrient("sodium", 5.0)
    assert result.resolved
    assert result.value == 5.0
    assert result.unit == "mg"


def test_sodium_boundary_7():
    """7mg rounds to nearest 5 (i.e., 5)."""
    result = round_nutrient("sodium", 7.0)
    assert result.resolved
    assert result.value == 5.0
    assert result.unit == "mg"


def test_sodium_boundary_140():
    """140mg rounds to nearest 5 (i.e., 140)."""
    result = round_nutrient("sodium", 140.0)
    assert result.resolved
    assert result.value == 140.0
    assert result.unit == "mg"


def test_sodium_boundary_141():
    """141mg rounds to nearest 10 (i.e., 140)."""
    result = round_nutrient("sodium", 141.0)
    assert result.resolved
    assert result.value == 140.0
    assert result.unit == "mg"


def test_sodium_boundary_145():
    """145mg rounds to nearest 10 (i.e., 150)."""
    result = round_nutrient("sodium", 145.0)
    assert result.resolved
    assert result.value == 150.0
    assert result.unit == "mg"


# --- Potassium (21 CFR 101.9(c)(5)) ---
# <5mg → 0; 5-140mg → nearest 5mg; >140mg → nearest 10mg


def test_potassium_boundary_below_5():
    """Values below 5mg round to 0."""
    result = round_nutrient("potassium", 4.0)
    assert result.resolved
    assert result.value == 0.0
    assert result.unit == "mg"


def test_potassium_boundary_at_5():
    """5mg rounds to nearest 5 (i.e., 5)."""
    result = round_nutrient("potassium", 5.0)
    assert result.resolved
    assert result.value == 5.0
    assert result.unit == "mg"


def test_potassium_boundary_141():
    """141mg rounds to nearest 10 (i.e., 140)."""
    result = round_nutrient("potassium", 141.0)
    assert result.resolved
    assert result.value == 140.0
    assert result.unit == "mg"


# --- Total Carbohydrate (21 CFR 101.9(c)(6)) ---
# <1g → 0; ≥1g → nearest 1g


def test_total_carbohydrate_boundary_below_1():
    """Values below 1g round to 0."""
    result = round_nutrient("total_carbohydrate", 0.9)
    assert result.resolved
    assert result.value == 0.0
    assert result.unit == "g"


def test_total_carbohydrate_boundary_at_1():
    """1g rounds to nearest 1 (i.e., 1)."""
    result = round_nutrient("total_carbohydrate", 1.0)
    assert result.resolved
    assert result.value == 1.0
    assert result.unit == "g"


def test_total_carbohydrate_boundary_1_4():
    """1.4g rounds to nearest 1 (i.e., 1)."""
    result = round_nutrient("total_carbohydrate", 1.4)
    assert result.resolved
    assert result.value == 1.0
    assert result.unit == "g"


def test_total_carbohydrate_boundary_1_5():
    """1.5g rounds to nearest 1 (i.e., 2)."""
    result = round_nutrient("total_carbohydrate", 1.5)
    assert result.resolved
    assert result.value == 2.0
    assert result.unit == "g"


# --- Dietary Fiber (21 CFR 101.9(c)(6)(i)) ---
# Same as Total Carbohydrate


def test_dietary_fiber_boundary_below_1():
    """Values below 1g round to 0."""
    result = round_nutrient("dietary_fiber", 0.9)
    assert result.resolved
    assert result.value == 0.0
    assert result.unit == "g"


def test_dietary_fiber_boundary_at_1():
    """1g rounds to nearest 1 (i.e., 1)."""
    result = round_nutrient("dietary_fiber", 1.0)
    assert result.resolved
    assert result.value == 1.0
    assert result.unit == "g"


# --- Protein (21 CFR 101.9(c)(7)) ---
# Same as Total Carbohydrate


def test_protein_boundary_below_1():
    """Values below 1g round to 0."""
    result = round_nutrient("protein", 0.9)
    assert result.resolved
    assert result.value == 0.0
    assert result.unit == "g"


def test_protein_boundary_at_1():
    """1g rounds to nearest 1 (i.e., 1)."""
    result = round_nutrient("protein", 1.0)
    assert result.resolved
    assert result.value == 1.0
    assert result.unit == "g"


# --- Error cases ---


def test_negative_value():
    """Negative values are rejected."""
    result = round_nutrient("calories", -1.0)
    assert not result.resolved
    assert result.reason == "negative_value"


def test_nan_value():
    """NaN values are rejected."""
    import math

    result = round_nutrient("calories", float("nan"))
    assert not result.resolved
    assert result.reason == "non_finite_value"


def test_infinity_value():
    """Infinity values are rejected."""
    result = round_nutrient("calories", float("inf"))
    assert not result.resolved
    assert result.reason == "non_finite_value"


def test_unknown_nutrient():
    """Unknown nutrients are rejected."""
    result = round_nutrient("unknown_nutrient", 100.0)
    assert not result.resolved
    assert result.reason == "unknown_nutrient"


# --- round_nutrient_with_text tests ---


def test_round_nutrient_with_text_calories():
    """Test formatted text output for calories."""
    result = round_nutrient_with_text("calories", 47.0)
    assert result.resolved
    assert result.value == 45.0


def test_round_nutrient_with_text_cholesterol():
    """Test formatted text output for cholesterol (2-5mg special case)."""
    result = round_nutrient_with_text("cholesterol", 3.0)
    assert result.resolved
    assert result.value == 3.0


def test_round_nutrient_with_text_zero():
    """Test formatted text output for zero values."""
    result = round_nutrient_with_text("total_fat", 0.3)
    assert result.resolved
    assert result.value == 0.0


def test_round_nutrient_with_text_unknown_nutrient():
    """Test error handling for unknown nutrients."""
    result = round_nutrient_with_text("unknown_nutrient", 100.0)
    assert not result.resolved
    assert result.reason == "unknown_nutrient"


# --- Version check ---


def test_version_string():
    """Verify the version string format."""
    assert VERSION == "rounding/fda-101.9-v1"
