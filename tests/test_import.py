"""The diary CSV importer: file in, the store's writer out, source='imported'."""
import csv

import pytest

import foodcore.importer as importer
from foodcore.importer import import_csv
from foodcore.store import add_entry, get_entries, init_db


#: The only sources the diary store will ever write.
VALID_SOURCES = ("manual", "imported")

#: The diary CSV's header row, exactly — and deliberately no source column.
CSV_HEADER = ("date", "meal", "kcal", "note")


def write_csv(path, rows, header=CSV_HEADER):
    """Write a diary CSV with the exact header the importer expects."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return str(path)


def sources_in(conn):
    """Every source value currently in the entries table."""
    return [
        row["source"]
        for row in conn.execute("SELECT source FROM entries").fetchall()
    ]


def test_import_csv_writes_only_imported_rows_and_counts_them(tmp_path):
    csv_path = write_csv(
        tmp_path / "diary.csv",
        [
            ("2026-01-01", "lunch", "300", "mom cooked"),
            ("2026-01-02", "dinner", "500", "date night"),
        ],
    )
    conn = init_db(str(tmp_path / "diary.sqlite"))

    assert import_csv(conn, csv_path) == 2

    rows = get_entries(conn)
    assert len(rows) == 2
    assert [row["source"] for row in rows] == ["imported", "imported"]
    assert [row["kcal"] for row in rows] == [300.0, 500.0]


def test_importing_the_same_csv_twice_is_a_safe_noop(tmp_path):
    """Re-importing must not duplicate or write a source outside the vocabulary."""
    csv_path = write_csv(
        tmp_path / "diary.csv",
        [
            ("2026-01-01", "lunch", "300", "mom cooked"),
            ("2026-01-02", "dinner", "500", "date night"),
        ],
    )
    conn = init_db(str(tmp_path / "diary.sqlite"))

    assert import_csv(conn, csv_path) == 2
    # The second run collides on the (date, meal) primary key and must not
    # overwrite, duplicate or write anything but 'imported'.
    assert import_csv(conn, csv_path) == 0

    rows = get_entries(conn)
    assert len(rows) == 2
    # Exactly one row per date/meal — the primary key held, nothing doubled up.
    assert len({(row["date"], row["meal"]) for row in rows}) == 2

    sources = sources_in(conn)
    assert sources
    assert all(source in VALID_SOURCES for source in sources)


def test_import_csv_skips_rows_with_blank_or_unparseable_fields(tmp_path):
    csv_path = write_csv(
        tmp_path / "diary.csv",
        [
            ("2026-01-01", "lunch", "300", "mom cooked"),
            ("2026-01-02", "lunch", "", "blank kcal"),  # skipped: blank required field
            ("", "lunch", "300", "blank date"),  # skipped: blank required field
            ("2026-01-03", "", "300", "blank meal"),  # skipped: blank required field
            ("2026-01-04", "snack", "lots", "bad kcal"),  # skipped: unparseable kcal
        ],
    )
    conn = init_db(str(tmp_path / "diary.sqlite"))

    assert import_csv(conn, csv_path) == 1

    rows = get_entries(conn)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-01-01"
    assert rows[0]["source"] == "imported"


def test_a_source_outside_the_vocabulary_is_refused_after_an_import(tmp_path):
    """The importer can only ever write 'imported'; the store refuses the rest."""
    csv_path = write_csv(tmp_path / "diary.csv", [("2026-01-01", "lunch", "300", "mom cooked")])
    conn = init_db(str(tmp_path / "diary.sqlite"))
    assert import_csv(conn, csv_path) == 1

    with pytest.raises(ValueError):
        add_entry(conn, "2026-01-02", "lunch", 300, "x", source="planned")


def test_importer_exposes_only_import_csv():
    assert importer.__all__ == ("import_csv",)
    assert not (set(importer.__all__) & {"insert", "update", "exec", "execute",
                                       "executemany", "replace", "upsert", "delete"})
    assert callable(importer.import_csv)
