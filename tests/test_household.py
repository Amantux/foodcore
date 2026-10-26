"""The curated vocabulary that makes a bare cooking word resolvable.

These tests exist because the feature was green against a 37-food fixture and
useless against a real 7,793-food import: "2 cups flour" refused as
`ambiguous_food` because USDA genuinely contains arrowroot, carob, millet,
potato and barley malt flour. Correct about the data, wrong about the question.
"""
from foodcore.rules.household_v1 import (
    CONFIDENCE,
    HOUSEHOLD_FOODS,
    VERSION,
    household_note,
    household_source_id,
)


def test_bare_cooking_words_name_a_specific_food():
    assert household_source_id("flour") == "168894"
    assert household_source_id("Flour") == "168894"       # case-insensitive
    assert household_source_id("  flour  ") == "168894"   # and whitespace


def test_a_word_outside_the_convention_gets_no_default():
    """MUTATION GUARD. The table must not become a fuzzy matcher: a near-miss
    here silently converts the WRONG food, which is the failure this module
    exists to prevent rather than cause."""
    # These are QUALIFIED variants: the cook named a specific flour, so the
    # bare-word convention must not overrule them. That is the property this
    # guard is for.
    #
    # "quinoa" used to sit in this list and has been promoted into the table.
    # It was only ever here as a word that happened to be absent, not as a word
    # that must stay absent -- unqualified quinoa means the uncooked grain, on
    # exactly the precedent that already makes "rice" raw and "oats" dry, and
    # its absence cost a correct 170 g/cup conversion. Replaced with a third
    # genuinely-qualified flour so the guard keeps testing what it is named for.
    for text in ("arrowroot flour", "barley malt flour", "teff flour",
                 "carob flour", ""):
        assert household_source_id(text) is None


def test_every_entry_explains_itself():
    """An uncited convention is indistinguishable from a guess. Each row names
    the food it resolves to and why, so a reviewer can check the claim without
    running anything."""
    for word, (fdc_id, description, why) in HOUSEHOLD_FOODS.items():
        assert fdc_id.isdigit(), f"{word}: {fdc_id!r} is not an FDC id"
        assert description.strip(), f"{word}: no description"
        # Deliberately a floor, not a prose-quality judgement: "exact" and
        # "British name" are complete justifications, and an earlier version of
        # this assertion failed them for being short, which measures the wrong
        # thing. What it must catch is an EMPTY or placeholder reason.
        assert len(why.strip()) >= 5, f"{word}: no reason given — {why!r}"
        assert why.strip().lower() not in {"todo", "tbd", "n/a", "?"}, word
        assert word == word.lower().strip(), f"{word!r} is not normalised"


def test_the_note_names_the_food_and_the_reason():
    note = household_note("cornflour")

    assert "Cornstarch" in note
    assert "false friend" in note     # the reason, not just the mapping


def test_the_convention_is_weaker_than_a_direct_match():
    """The WEIGHT is measured; the IDENTIFICATION is a cultural convention, and
    a chain is only as strong as its weakest link."""
    assert CONFIDENCE < 0.8
    assert VERSION.startswith("household/")


def test_raw_and_cooked_stay_separate_foods():
    """FR-01's rule survives the convention layer: these are different foods
    with different weights per cup (185 g vs 158 g), not two names for one."""
    assert household_source_id("rice") != household_source_id("cooked rice")


def test_every_id_names_a_real_food_with_the_description_claimed(shipped_dataset):
    """The citations must be CHECKED, not merely present.

    `test_every_entry_explains_itself` proves each row has a description; this
    proves the description is the food that id actually names. Nothing else in
    the suite did, and the table is a hand-written list of 73 numeric ids whose
    whole value is that a reviewer can trust them.

    The hazard is concrete and was hit repeatedly while building this table:
    ids transcribed by hand pointed at a MARS candy bar, millet, pumpkin seeds,
    and a cooked row where the raw one was meant. A wrong id here does not
    raise — it silently returns a confident weight for the wrong food, which is
    the one failure this module exists to prevent.

    Also catches a USDA re-release renumbering or restating a food: the table
    then fails loudly instead of drifting.
    """
    missing, mismatched = [], []
    for word, (fdc_id, description, _why) in HOUSEHOLD_FOODS.items():
        record = shipped_dataset.food_by_source_id(fdc_id)
        if record is None:
            missing.append(f"{word}: id {fdc_id} is not in the dataset")
            continue
        # Prefix, not equality: SR Legacy appends parentheticals like
        # "(Includes foods for USDA's Food Distribution Program)" that carry no
        # meaning and would make the table unreadable if quoted in full.
        actual = record.description
        if not actual.startswith(description):
            mismatched.append(
                f"{word}: table says {description!r}, dataset says {actual!r}")

    assert not missing, "\n".join(missing)
    assert not mismatched, "\n".join(mismatched)


def test_the_new_entries_actually_carry_the_weight_they_were_added_for(shipped_dataset):
    """Each of these was added because a real line converted wrongly or not at
    all. Pinning the weight proves the entry does the job rather than merely
    existing — an id that resolves but has no portion row for the measure a
    cook uses is a no-op.
    """
    expected = {
        "whole wheat flour": ("cup", 120.0),
        "bread flour": ("cup", 137.0),
        "powdered sugar": ("cup", 120.0),
        "cornmeal": ("cup", 122.0),
        "breadcrumbs": ("cup", 108.0),
        "molasses": ("cup", 337.0),
        "ketchup": ("cup", 240.0),
        "lentils": ("cup", 192.0),
        "quinoa": ("cup", 170.0),
        "cream cheese": ("cup", 232.0),
        "cocoa powder": ("cup", 86.0),
        "vinegar": ("cup", 238.0),
        "cream of tartar": ("tsp", 3.0),
        "garlic powder": ("tsp", 3.1),
        "parsley": ("tbsp", 3.8),
    }
    wrong = []
    for word, (measure, grams) in expected.items():
        record = shipped_dataset.food_by_source_id(HOUSEHOLD_FOODS[word][0])
        rows = [p for p in record.portions if p.measure == measure]
        if not any(abs(p.grams_per_unit - grams) < 0.5 for p in rows):
            have = ", ".join(f"{p.grams_per_unit}{p.measure}" for p in rows) or "none"
            wrong.append(f"{word}: expected {grams} g/{measure}, dataset has {have}")

    assert not wrong, "\n".join(wrong)
