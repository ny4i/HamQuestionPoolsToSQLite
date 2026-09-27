"""General (Element 3) pool. Expected values come from the errata text at the top of the
source file ("leaving N questions"), not from the parser's own output."""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_pool_db as b  # noqa: E402

GENERAL_MD = ROOT / "2023-2027-General-Class-Question-Pool.md"
EXTRA_MD = ROOT / "2024-2028-Extra-Class-Question-Pool.md"


@pytest.fixture(scope="module")
def pool():
    return b.parse_pool(GENERAL_MD.read_text(encoding="utf-8"))


def by_id(pool):
    return {x["id"]: x for x in pool["questions"]}


def test_identity(pool):
    assert pool["pool_name"] == "2023-2027 General Class (Element 3)"
    assert pool["element"] == "3"


def test_counts(pool):
    assert len(pool["questions"]) == 423
    assert sorted(pool["deleted"]) == ["G1A04", "G1C08", "G1C09", "G1C10", "G1E09",
                                       "G6B09", "G8C01", "G9C06", "G9D13"]
    assert len(pool["subelements"]) == 10
    assert len(pool["groups"]) == 35


def test_exam_weights_sum_to_35(pool):
    assert sum(v[1] for v in pool["subelements"].values()) == 35


def test_errata_leaving_counts(pool):
    counts = {}
    for x in pool["questions"]:
        counts[x["group_id"]] = counts.get(x["group_id"], 0) + 1
    assert {g: counts[g] for g in ["G1A", "G1C", "G1E", "G6B", "G8C", "G9C", "G9D"]} == \
        {"G1A": 10, "G1C": 8, "G1E": 11, "G6B": 11, "G8C": 15, "G9C": 11, "G9D": 12}


def test_errata_text_present_in_body(pool):
    q = by_id(pool)
    assert q["G1A05"]["choice_d"] == "All these choices are correct"
    assert q["G2E12"]["choice_d"] == "All these choices are correct"
    assert "structure not near a public use airport" in q["G1B01"]["question"]
    assert "10.140 MHz" in q["G1C01"]["question"] and "transmitter power" in q["G1C01"]["question"]
    assert "input signal is applied to the secondary" in q["G5C02"]["question"]
    assert q["G9B05"]["question"].endswith("at elevation angles higher than about 45 degrees?")
    assert q["G9C09"]["question"].startswith("In free space,")
    assert q["G9D01"]["choice_c"] == "A horizontal dipole placed at approximately 1/2 wavelength above the ground"
    assert q["G9D09"]["choice_a"] == "Directional receiving for MF and low HF bands"
    assert "less than 1/10 wavelength" in q["G9D10"]["question"]
    assert "24.930 and 28.200" in q["G1E10"]["question"]


def test_missing_space_after_choice_letter(pool):
    # 'D.A DX spotting system...' is a typo in the official PDF too.
    assert by_id(pool)["G2E02"]["choice_d"] == "A DX spotting system using a network of software defined radios"


def test_titles(pool):
    titles = {k: v[0] for k, v in pool["subelements"].items()}
    assert titles["G1"] == "Commission’s Rules"
    assert titles["G0"] == "Electrical and RF Safety"
    assert titles["G9"] == "Antennas and Feed Lines"
    assert list(titles)[-1] == "G0"


def test_syllabus_not_confused_by_errata_subelement_lines(pool):
    # The errata preamble repeats 'SUBELEMENT G1 ... 55 Questions'; only the syllabus counts.
    assert pool["subelements"]["G1"][2] == 0
    assert pool["groups"]["G2B"] == "Operating effectively; band plans; drills and emergencies; RACES operation"


def test_figures(pool):
    assert {x["id"]: x["figure"] for x in pool["questions"] if x["figure"]} == {"G7A12": "G7-1", "G7A13": "G7-1"}


def test_refuses_to_write_into_other_pools_db(pool, tmp_path):
    path = tmp_path / "extra.db"
    b.write_db(b.parse_pool(EXTRA_MD.read_text(encoding="utf-8")), path, "extra.md").close()
    with pytest.raises(b.WrongPoolError, match="Extra"):
        b.write_db(pool, path, "general.md")
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM questions WHERE status='active'").fetchone()[0] == 599
    assert conn.execute("SELECT COUNT(*) FROM questions WHERE id LIKE 'G%'").fetchone()[0] == 0
    conn.close()


def test_cli_requires_db(capsys):
    with pytest.raises(SystemExit):
        b.main(["--md", str(GENERAL_MD)])


def test_provenance_recorded_per_pool(pool, tmp_path):
    path = tmp_path / "g.db"
    b.write_db(pool, path, "general.md").close()
    meta = dict(sqlite3.connect(path).execute("SELECT key, value FROM pool_meta").fetchall())
    assert meta["license"] == "Public Domain"
    assert "2023-2027 General, Element 3" in meta["license_statement"]
    assert meta["source_url"].endswith("2023-2027-general-question-pool-release")


def test_unknown_pool_gets_no_license_claim(pool, tmp_path):
    path = tmp_path / "x.db"
    b.write_db(dict(pool, pool_name="2027-2031 General Class (Element 3)"), path, "future.md").close()
    meta = dict(sqlite3.connect(path).execute("SELECT key, value FROM pool_meta").fetchall())
    assert "license" not in meta and "source_url" not in meta
    assert meta["publisher"] == "NCVEC Question Pool Committee"
