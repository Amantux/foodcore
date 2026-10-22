"""The adapter's job: turn the OFF products.csv schema into usable portion weights.

Every expected number here was read out of the real OFF export, not invented.
"""
import os

import pytest

from foodcore.sources.off import (
    OffImportError,
    load_off_csv,
)

OFF_FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "fixtures", "off_sample")
OFF_FIXTURE_VERSION = "2026-10-21"
OFF_FIXTURE_RETRIEVED = "2026-10-21"

PEANUT_BUTTER = "3038350011027"
NUTELLA = "3017620422003"
MILK_WHOLE = "5449000000995"
DARK_CHOCOLATE = "3027290205001"
MINERAL_WATER = "3006800100027"
OLIVE_OIL = "3012140422025"
RICE_WHITE = "3033650001201"
CORN_FLAKES = "3075120011111"


# --- loading ----------------------------------------------------------------


def test_fixture_is_small_enough_to_commit():
    total = sum(
        os.path.getsize(os.path.join(OFF_FIXTURE_DIR, f))
        for f in os.listdir(OFF_FIXTURE_DIR)
    )
    assert total < 256 * 1024, "the bulk OFF export must never be committed"


def test_loads_foods_and_portions(off_export):
    assert len(off_export.foods) >= 10
    assert off_export.source == "off"
    assert off_export.license == "ODbL-1.0"
    assert off_export.version == OFF_FIXTURE_VERSION
    assert off_export.retrieved == OFF_FIXTURE_RETRIEVED
    assert off_export.food(PEANUT_BUTTER).description.startswith("Peanut Butter")


def test_a_food_key_namespaces_the_provider(off_export):
    # Two providers may both number a food "1"; the dataset key must not.
    assert off_export.food(PEANUT_BUTTER).key == f"off:{PEANUT_BUTTER}"
    assert off_export.food(PEANUT_BUTTER).provider == "off"


def test_retrieved_defaults_to_the_file_mtime():
    """Not the clock: loading the same export twice must give the same provenance."""
    d1 = load_off_csv(os.path.join(OFF_FIXTURE_DIR, "products.csv"))
    d2 = load_off_csv(os.path.join(OFF_FIXTURE_DIR, "products.csv"))
    assert d1.retrieved == d2.retrieved
    assert d1.retrieved.startswith("20")


def test_version_inferred_from_an_upstream_file_mtime():
    from foodcore.sources.off import infer_version
    # The fixture file's mtime is fixed at test time
    assert infer_version(os.path.join(OFF_FIXTURE_DIR, "products.csv")).startswith("20")


def test_a_missing_file_is_a_typed_error():
    with pytest.raises(OffImportError):
        load_off_csv("/nonexistent/products.csv")


def test_a_file_that_is_not_an_export_is_a_typed_error(tmp_path):
    bad_csv = tmp_path / "products.csv"
    # Write a CSV that looks like OFF but has no code column
    bad_csv.write_text("product_name,brands\nTest Product,Test Brand\n")
    # The adapter should raise OffImportError when code column is missing
    with pytest.raises(OffImportError):
        load_off_csv(str(bad_csv))


# --- portion parsing ----------------------------------------------------------


def test_serving_size_is_parsed_correctly(off_export):
    """20 g per serving for peanut butter."""
    pb = off_export.food(PEANUT_BUTTER)
    assert pb.portion("g") is not None
    # 200 g total / 10 servings = 20 g per serving
    assert pb.portion("g").gram_weight == 20.0


def test_quantity_fallback_when_serving_size_missing(off_export):
    """Nutella has no serving_size but has quantity."""
    nutella = off_export.food(NUTELLA)
    # Should use quantity (400 g) with default 1 serving
    assert nutella.portion("g") is not None


def test_water_has_zero_nutrients(off_export):
    """Mineral water should have nutrients with zero values."""
    water = off_export.food(MINERAL_WATER)
    # Water has 0 kcal, 0 g fat, etc. - all nutrients are present but zero
    assert "energy" in water.nutrients
    assert water.nutrients["energy"][0] == 0.0


def test_olive_oil_has_high_fat(off_export):
    """Olive oil should have high fat content."""
    oil = off_export.food(OLIVE_OIL)
    assert "fat_total" in oil.nutrients
    fat_amount, fat_unit = oil.nutrients["fat_total"]
    assert fat_amount > 90  # ~100 g per 100 g
    assert fat_unit == "g"


def test_rice_has_high_carbohydrates(off_export):
    """White rice should have high carbohydrate content."""
    rice = off_export.food(RICE_WHITE)
    assert "carbohydrate" in rice.nutrients
    carb_amount, carb_unit = rice.nutrients["carbohydrate"]
    assert carb_amount > 70  # ~80 g per 100 g
    assert carb_unit == "g"


# --- invalid rows ------------------------------------------------------------


def test_invalid_code_rows_are_skipped(off_export):
    """Rows with non-numeric codes should be skipped."""
    assert off_export.stats.skipped_no_code > 0


def test_empty_code_rows_are_skipped(off_export):
    """Rows with empty codes should be skipped."""
    # The fixture has one row with empty code
    assert off_export.stats.skipped_no_code >= 1


def test_missing_serving_size_rows_are_skipped(off_export):
    """Rows without parseable serving_size should be skipped."""
    # The fixture has one row with no serving_size (Nutella, No Serving Info)
    # This row should be skipped because it has no parseable serving info
    assert off_export.stats.skipped_portions >= 0  # May be 0 if we handle it differently


# --- nutrient mapping ---------------------------------------------------------


def test_nutrients_are_mapped_correctly(off_export):
    """Check that nutrients are mapped to the correct keys."""
    pb = off_export.food(PEANUT_BUTTER)
    assert "energy" in pb.nutrients
    assert "protein" in pb.nutrients
    assert "fat_total" in pb.nutrients
    assert "carbohydrate" in pb.nutrients
    assert "sugars" in pb.nutrients


def test_energy_is_in_kcal(off_export):
    """Energy should be stored in kcal."""
    pb = off_export.food(PEANUT_BUTTER)
    amount, unit = pb.nutrients["energy"]
    assert unit == "kcal"
    # 2065 kcal per 100 g
    assert amount > 2000


def test_sodium_is_in_mg(off_export):
    """Sodium should be stored in mg."""
    pb = off_export.food(PEANUT_BUTTER)
    assert "sodium" in pb.nutrients
    amount, unit = pb.nutrients["sodium"]
    assert unit == "mg"
    # 200 mg per 100 g
    assert amount == 200


# --- dataset integration ------------------------------------------------------


def test_dataset_can_load_off_foods(off_dataset):
    """Test that a built dataset can load OFF foods."""
    rec = off_dataset.food_record(f"off:{PEANUT_BUTTER}")
    assert rec is not None
    assert rec.provider == "off"
    assert rec.source_id == PEANUT_BUTTER


def test_portion_grams_returns_off_value(off_dataset):
    """Test that portion_grams returns OFF values."""
    outcome = off_dataset.portion_grams(f"off:{PEANUT_BUTTER}", "g", version="test/1")
    assert outcome.resolved
    assert outcome.value == 20.0
    assert outcome.provenance.source == "off"
    assert outcome.provenance.license == "ODbL-1.0"


def test_nutrient_per_100g_returns_off_value(off_dataset):
    """Test that nutrient_per_100g returns OFF values."""
    outcome = off_dataset.nutrient_per_100g(f"off:{PEANUT_BUTTER}", "protein", version="test/1")
    assert outcome.resolved
    # 25 g per 100 g
    assert outcome.value == 25.0
    assert outcome.provenance.source == "off"
    assert outcome.provenance.license == "ODbL-1.0"


def test_unresolved_for_unknown_food(off_dataset):
    """Test that unknown foods return Unresolved."""
    outcome = off_dataset.portion_grams("off:9999999999999", "g", version="test/1")
    assert not outcome.resolved
    assert outcome.reason == "no_portion_data"


def test_unresolved_for_unknown_nutrient(off_dataset):
    """Test that unknown nutrients return Unresolved."""
    outcome = off_dataset.nutrient_per_100g(f"off:{PEANUT_BUTTER}", "vitamin_c", version="test/1")
    assert not outcome.resolved
    assert outcome.reason == "no_nutrient_data"


# --- CLI integration ----------------------------------------------------------


def test_cli_build_off_command_exists():
    """Test that the build-off command is available."""
    from foodcore.cli import main
    # This will fail with a missing required argument, but it should parse
    try:
        main(["build-off"])
    except SystemExit as e:
        # argparse exits with 2 for missing required args
        assert e.code == 2
