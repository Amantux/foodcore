"""The build/inspect CLI, driven the way an operator drives it.

The USDA fixtures below are shaped like a FoodData Central CSV export but hold
invented ids and weights — they exercise the importer's structure, not USDA's
numbers, and nothing from them is ever shipped. (The REAL rows live in
`tests/fixtures/usda_fdc_sample` and are asserted in `test_usda.py`.)
"""
import pytest

from foodcore import load_dataset, rule_version
from foodcore.cli import main
from foodcore.sources.usda import UsdaImportError, load_fdc_csv

VERSION = rule_version("convert")


def write_fdc_export(dirpath):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "food.csv").write_text(
        "fdc_id,data_type,description\n"
        "1001,foundation_food,\"Flour, wheat, white\"\n"
        "1002,branded_food,\"Tomatoes, canned\"\n"
    )
    (dirpath / "measure_unit.csv").write_text("id,name\n9,cups\n10,undetermined\n")
    (dirpath / "food_portion.csv").write_text(
        "id,fdc_id,amount,measure_unit_id,portion_description,modifier,gram_weight\n"
        "1,1001,1,9,,,125\n"
        "2,1001,2,9,,,250\n"            # 2 cups = 250 g -> 125 g per cup
        "3,1002,1,10,,,400\n"           # unnameable measure -> skipped
    )
    (dirpath / "nutrient.csv").write_text(
        "id,name,unit_name\n"
        "1008,Energy,KCAL\n"
        "1003,Protein,G\n"
        "9999,Fluoride,UG\n"          # unmapped -> reported, not dropped silently
    )
    (dirpath / "food_nutrient.csv").write_text(
        "fdc_id,nutrient_id,amount\n"
        "1001,1008,364\n"
        "1001,1003,10.3\n"
        "1001,9999,1.1\n"
        "1002,1008,\n"                # no amount -> omitted, so lookups say unknown
    )
    return dirpath


def rows(dirpath, **kwargs):
    export = load_fdc_csv(str(dirpath), version="April 2025",
                          retrieved="2025-04-01", **kwargs)
    foods, portions, nutrients = export.rows()
    return foods, portions, nutrients, export.stats


# --- the importer -------------------------------------------------------

def test_the_parser_reads_foods_portions_and_mapped_nutrients(tmp_path):
    foods, portions, nutrients, stats = rows(write_fdc_export(tmp_path))

    assert {f["key"] for f in foods} == {"usda:1001", "usda:1002"}
    assert {(p["measure"], p["grams"], p["amount"]) for p in portions} == {
        ("cup", 125.0, 1.0), ("cup", 250.0, 2.0)
    }
    assert {(n["nutrient"], n["per_100g"]) for n in nutrients} == {
        ("calories", 364.0), ("protein", 10.3)
    }
    assert stats.skipped_portions == 1


def test_a_portion_row_keeps_both_the_published_amount_and_its_weight(tmp_path):
    _, portions, _, _ = rows(write_fdc_export(tmp_path))

    # "2 cups = 250 g" is stored as published, not pre-divided: a reader must
    # be able to see what upstream said. `grams_per_unit` does the division, so
    # both source rows describe the same 125 g cup.
    dataset_rows = {(p["amount"], p["grams"]) for p in portions}
    assert dataset_rows == {(1.0, 125.0), (2.0, 250.0)}
    assert {p["grams"] / p["amount"] for p in portions} == {125.0}


def test_branded_values_are_declared_not_measured(tmp_path):
    write_fdc_export(tmp_path)
    (tmp_path / "food_portion.csv").write_text(
        "id,fdc_id,amount,measure_unit_id,portion_description,modifier,gram_weight\n"
        "1,1002,1,9,,,400\n"
    )

    _, portions, _, _ = rows(tmp_path)

    # A manufacturer's label is a weaker kind of evidence than a lab analysis,
    # and recording it as "measured" would erase that difference forever.
    assert [p["method"] for p in portions] == ["declared"]


def test_unmapped_nutrients_are_reported_not_silently_dropped(tmp_path):
    _, _, _, stats = rows(write_fdc_export(tmp_path))

    assert "Fluoride" in stats.unmapped_nutrients
    assert "Fluoride" in stats.report()


def test_a_nutrient_with_no_amount_is_omitted_so_lookups_say_unknown(tmp_path):
    _, _, nutrients, _ = rows(write_fdc_export(tmp_path))

    # Writing 0 here is the exact defect this package exists to prevent.
    assert not [n for n in nutrients if n["food_key"] == "usda:1002"]


def test_data_type_filter_limits_the_build(tmp_path):
    foods, _, _, _ = rows(write_fdc_export(tmp_path),
                          data_types=("foundation_food",))

    assert [f["key"] for f in foods] == ["usda:1001"]


def test_limit_stops_after_n_foods(tmp_path):
    foods, _, _, _ = rows(write_fdc_export(tmp_path), limit=1)

    assert len(foods) == 1


def test_a_directory_that_is_not_an_export_is_a_typed_error(tmp_path):
    with pytest.raises(UsdaImportError) as exc:
        load_fdc_csv(str(tmp_path))

    assert "food.csv" in str(exc.value)


# --- the CLI -----------------------------------------------------------

def test_build_usda_writes_a_loadable_dataset(tmp_path, capsys):
    export = write_fdc_export(tmp_path / "export")
    out = tmp_path / "fc.sqlite"

    code = main(["build-usda", "--fdc-dir", str(export), "--out", str(out),
                 "--dataset-version", "April 2025", "--retrieved", "2025-04-01"])

    assert code == 0
    assert "foods" in capsys.readouterr().out
    dataset = load_dataset(str(out))
    outcome = dataset.portion_grams("usda:1001", "cup", version=VERSION)
    assert outcome.value == 125.0
    assert outcome.provenance.license == "CC0-1.0"
    assert outcome.provenance.retrieved == "2025-04-01"


def test_build_usda_records_the_snapshot_in_the_registry(tmp_path):
    export = write_fdc_export(tmp_path / "export")
    out = tmp_path / "fc.sqlite"
    main(["build-usda", "--fdc-dir", str(export), "--out", str(out),
          "--dataset-version", "April 2025"])

    record = load_dataset(str(out)).sources[0]

    assert (record.provider, record.dataset_version) == ("usda", "April 2025")
    assert record.license == "CC0-1.0"
    # The skip/unmapped report is kept with the snapshot, so months later a
    # host can see what this dataset does NOT contain.
    assert "Fluoride" in record.notes


def test_build_usda_on_a_bad_directory_exits_nonzero_with_a_message(tmp_path, capsys):
    code = main(["build-usda", "--fdc-dir", str(tmp_path), "--out",
                 str(tmp_path / "x.sqlite"), "--dataset-version", "v1"])

    assert code == 1
    assert "foodcore:" in capsys.readouterr().err


def test_build_usda_on_a_bad_directory_writes_no_dataset(tmp_path):
    out = tmp_path / "x.sqlite"

    main(["build-usda", "--fdc-dir", str(tmp_path), "--out", str(out),
          "--dataset-version", "v1"])

    assert not out.exists()
    assert list(tmp_path.iterdir()) == []


def test_an_unwritable_out_path_is_a_curated_message_not_a_traceback(
    tmp_path, capsys
):
    """MUTATION GUARD for the CLI's error boundary.

    The parse half was inside a `try` and the STORAGE half was not, so a
    `--out` under a non-existent directory printed a raw
    `sqlite3.OperationalError` traceback — in a function whose own comment
    promises "not a raw traceback". A malformed row escaped the same way,
    printing the whole row.
    """
    export = write_fdc_export(tmp_path / "export")

    code = main(["build-usda", "--fdc-dir", str(export),
                 "--out", str(tmp_path / "no_such_dir" / "fc.sqlite"),
                 "--dataset-version", "v1"])

    err = capsys.readouterr().err
    assert code == 1
    assert err.startswith("foodcore:")
    assert "Traceback" not in err
    assert "sqlite3" not in err.lower()


def test_the_build_says_so_when_rows_collapse_on_a_primary_key(tmp_path, capsys):
    """Two portion rows sharing every key column but `grams`.

    The writer counts what landed, so the operator is told the parsed count and
    the stored count differ. Printing two numbers and hoping somebody compares
    them is how 8 missing portion weights go unnoticed.
    """
    export = write_fdc_export(tmp_path / "export")
    (export / "food_portion.csv").write_text(
        "id,fdc_id,amount,measure_unit_id,portion_description,modifier,gram_weight\n"
        "dup,1001,1,9,,,125\n"
        "dup,1001,1,9,,,160\n"
    )

    code = main(["build-usda", "--fdc-dir", str(export),
                 "--out", str(tmp_path / "fc.sqlite"),
                 "--dataset-version", "v1"])

    assert code == 0
    assert "collapsed on a primary key" in capsys.readouterr().err


def test_info_describes_the_bundled_fallback_as_minimal(monkeypatch, capsys):
    from foodcore.datasets import DATASET_ENV_VAR

    monkeypatch.delenv(DATASET_ENV_VAR, raising=False)

    assert main(["info"]) == 0
    out = capsys.readouterr().out
    assert "bundled minimal dataset" in out
    assert "NOTE:" in out


def test_info_on_a_built_dataset_lists_its_sources(tmp_path, capsys):
    export = write_fdc_export(tmp_path / "export")
    out = tmp_path / "fc.sqlite"
    main(["build-usda", "--fdc-dir", str(export), "--out", str(out),
          "--dataset-version", "April 2025"])

    main(["info", "--dataset", str(out)])

    printed = capsys.readouterr().out
    assert "usda April 2025" in printed
    assert "CC0-1.0" in printed


def test_info_on_a_missing_dataset_exits_nonzero(tmp_path, capsys):
    code = main(["info", "--dataset", str(tmp_path / "absent.sqlite")])

    assert code == 1
    assert "absent.sqlite" in capsys.readouterr().err


# --- lookup -------------------------------------------------------------


def test_lookup_resolves_a_confident_food(tmp_path, capsys):
    export = write_fdc_export(tmp_path / "export")
    out = tmp_path / "fc.sqlite"
    main(["build-usda", "--fdc-dir", str(export), "--out", str(out),
          "--dataset-version", "April 2025"])

    code = main(["lookup", "Flour, wheat, white", "--dataset", str(out)])
    assert code == 0
    out_text = capsys.readouterr().out
    assert "Resolved:" in out_text
    assert "Flour, wheat, white" in out_text
    assert "usda:1001" in out_text


def test_lookup_shows_candidates_when_ambiguous(tmp_path, capsys):
    # Create a dataset with multiple rice variants for ambiguous testing
    export_dir = tmp_path / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "food.csv").write_text(
        "fdc_id,data_type,description\n"
        "1001,foundation_food,\"Rice, white, long-grain, raw\"\n"
        "1002,foundation_food,\"Rice, white, long-grain, cooked\"\n"
        "1003,foundation_food,\"Rice, white, medium-grain, raw\"\n"
        "1004,branded_food,\"Tomatoes, canned\"\n"
    )
    (export_dir / "measure_unit.csv").write_text("id,name\n9,cups\n10,undetermined\n")
    (export_dir / "food_portion.csv").write_text(
        "id,fdc_id,amount,measure_unit_id,portion_description,modifier,gram_weight\n"
        "1,1001,1,9,,,185\n"
        "2,1001,2,9,,,370\n"
        "3,1002,1,9,,,158\n"
        "4,1003,1,9,,,175\n"
    )
    (export_dir / "nutrient.csv").write_text(
        "id,name,unit_name\n"
        "1008,Energy,KCAL\n"
        "1003,Protein,G\n"
    )
    (export_dir / "food_nutrient.csv").write_text(
        "fdc_id,nutrient_id,amount\n"
        "1001,1008,365\n"
        "1001,1003,7.1\n"
        "1002,1008,130\n"
        "1002,1003,2.7\n"
        "1003,1008,365\n"
        "1003,1003,7.2\n"
    )

    out = tmp_path / "fc.sqlite"
    main(["build-usda", "--fdc-dir", str(export_dir), "--out", str(out),
          "--dataset-version", "April 2025"])

    code = main(["lookup", "Rice", "--dataset", str(out)])
    assert code == 0
    out_text = capsys.readouterr().out
    assert "Ambiguous:" in out_text
    assert "Rice, white, long-grain, raw" in out_text
    assert "Rice, white, long-grain, cooked" in out_text


def test_lookup_handles_no_match_cleanly(tmp_path, capsys):
    export = write_fdc_export(tmp_path / "export")
    out = tmp_path / "fc.sqlite"
    main(["build-usda", "--fdc-dir", str(export), "--out", str(out),
          "--dataset-version", "April 2025"])

    code = main(["lookup", "nonsensefood12345", "--dataset", str(out)])
    assert code == 0
    out_text = capsys.readouterr().out
    assert "No matches for" in out_text
    assert "nonsensefood12345" in out_text


def test_lookup_uses_bundled_fallback_when_no_dataset(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("FOODCORE_DATASET", raising=False)
    # A nonsense query on the minimal dataset should still work (no traceback)
    code = main(["lookup", "nonsensefood12345"])
    assert code == 0
    out_text = capsys.readouterr().out
    assert "No matches for" in out_text


def test_lookup_limit_flag_controls_candidate_count(tmp_path, capsys):
    # Create a dataset with multiple rice variants
    export_dir = tmp_path / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "food.csv").write_text(
        "fdc_id,data_type,description\n"
        "1001,foundation_food,\"Rice, white, long-grain, raw\"\n"
        "1002,foundation_food,\"Rice, white, long-grain, cooked\"\n"
        "1003,foundation_food,\"Rice, white, medium-grain, raw\"\n"
        "1004,branded_food,\"Tomatoes, canned\"\n"
    )
    (export_dir / "measure_unit.csv").write_text("id,name\n9,cups\n10,undetermined\n")
    (export_dir / "food_portion.csv").write_text(
        "id,fdc_id,amount,measure_unit_id,portion_description,modifier,gram_weight\n"
        "1,1001,1,9,,,185\n"
        "2,1001,2,9,,,370\n"
        "3,1002,1,9,,,158\n"
        "4,1003,1,9,,,175\n"
    )
    (export_dir / "nutrient.csv").write_text(
        "id,name,unit_name\n"
        "1008,Energy,KCAL\n"
        "1003,Protein,G\n"
    )
    (export_dir / "food_nutrient.csv").write_text(
        "fdc_id,nutrient_id,amount\n"
        "1001,1008,365\n"
        "1001,1003,7.1\n"
        "1002,1008,130\n"
        "1002,1003,2.7\n"
        "1003,1008,365\n"
        "1003,1003,7.2\n"
    )

    out = tmp_path / "fc.sqlite"
    main(["build-usda", "--fdc-dir", str(export_dir), "--out", str(out),
          "--dataset-version", "April 2025"])

    code = main(["lookup", "Rice", "--dataset", str(out), "--limit", "1"])
    assert code == 0
    out_text = capsys.readouterr().out
    # Should show only one candidate (the limit flag works)
    assert "1. 1002 Rice, white, long-grain, cooked" in out_text
    # Should not show the second candidate (the limit is respected)
    assert "... and 2 more" in out_text


# --- lookup --measure / --nutrient: same engines the host apps call -----

def test_lookup_measure_prints_resolved_value_with_provenance(tmp_path, capsys):
    export = write_fdc_export(tmp_path)
    out = tmp_path / "fc.sqlite"
    main(["build-usda", "--fdc-dir", str(export), "--out", str(out),
          "--dataset-version", "April 2025"])

    code = main(["lookup", "Flour, wheat, white", "--dataset", str(out),
                 "--measure", "cup"])
    assert code == 0
    out_text = capsys.readouterr().out
    # "cup" row 1 on 1001 is 125 g -> the Outcome prints value + unit and
    # the source row's provenance (USDA snapshot, license).
    assert "Measure 'cup': 125 g" in out_text
    assert "usda:1001" in out_text
    assert "CC0-1.0" in out_text


def test_lookup_measure_when_food_has_no_portions_prints_reason(tmp_path,
                                                                  capsys):
    export = write_fdc_export(tmp_path)
    out = tmp_path / "fc.sqlite"
    main(["build-usda", "--fdc-dir", str(export), "--out", str(out),
          "--dataset-version", "April 2025"])

    # 1002's only portion row names the unnameable measure (id 10), which the
    # importer skips -> `portion_grams` says no_portion_data, not zero grams.
    code = main(["lookup", "Tomatoes, canned", "--dataset", str(out),
                 "--measure", "cup"])
    assert code == 0
    out_text = capsys.readouterr().out
    assert "unresolved [no_portion_data]" in out_text


def test_lookup_nutrient_prints_resolved_value_and_unknown_reason(tmp_path,
                                                                    capsys):
    export = write_fdc_export(tmp_path)
    out = tmp_path / "fc.sqlite"
    main(["build-usda", "--fdc-dir", str(export), "--out", str(out),
          "--dataset-version", "April 2025"])

    main(["lookup", "Flour, wheat, white", "--dataset", str(out),
          "--nutrient", "energy"])
    main(["lookup", "Tomatoes, canned", "--dataset", str(out),
          "--nutrient", "energy"])
    out_text = capsys.readouterr().out
    # 1001: energy 364 kcal published; 1002: nutrient row has no amount,
    # so the record carries no energy -> unknown, never zero.
    # (The engine normalises the source "KCAL" unit to "kcal"; the
    # original expectation here ("364 KCAL") was never run and did not
    # match actual behaviour.)
    assert "Nutrient 'energy': 364 kcal" in out_text
    assert "Nutrient 'energy': unresolved [no_nutrient_data]" in out_text


def test_lookup_ambiguous_query_shows_candidates_not_a_measure_guess(
        tmp_path, capsys):
    # An ambiguous query prints candidates and skips the measure lookup —
    # there is no single record to ask — and still exits 0 without traceback.
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "food.csv").write_text(
        "fdc_id,data_type,description\n"
        "1001,foundation_food,\"Rice, white, long-grain, cooked\"\n"
        "1002,foundation_food,\"Rice, white, long-grain, raw\"\n"
    )
    (export_dir / "measure_unit.csv").write_text(
        "id,name\n9,cups\n10,Serving\n")
    (export_dir / "food_portion.csv").write_text(
        "id,fdc_id,amount,measure_unit_id,portion_description,modifier,"
        "gram_weight\n"
        "1,1001,1,9,,,185\n2,1002,1,9,,,158\n"
    )
    out = tmp_path / "fc.sqlite"
    main(["build-usda", "--fdc-dir", str(export_dir), "--out", str(out),
          "--dataset-version", "April 2025"])

    code = main(["lookup", "Rice", "--dataset", str(out), "--measure",
                 "cup"])
    assert code == 0
    out_text = capsys.readouterr().out
    assert "Ambiguous: 2 candidates" in out_text
    # No Measure/Nutrient line: nothing was resolved, so nothing was looked up.
    assert "Measure" not in out_text
