import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_pool_db as b  # noqa: E402

MD = (ROOT / "2024-2028-Extra-Class-Question-Pool.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pool():
    return b.parse_pool(MD)


@pytest.fixture
def db(pool, tmp_path):
    path = tmp_path / "pool.db"
    b.write_db(pool, path, "test.md").close()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn, path
    conn.close()


def q(conn, sql, *params):
    return conn.execute(sql, params).fetchall()


# --- parsing -------------------------------------------------------------

def test_counts(pool):
    assert len(pool["questions"]) == 599
    assert sorted(pool["deleted"]) == ["E2A13", "E4D05", "E6D07", "E9E10"]
    assert len(pool["subelements"]) == 10
    assert len(pool["groups"]) == 50


def test_active_counts_per_subelement(pool):
    counts = {}
    for x in pool["questions"]:
        counts[x["subelement_id"]] = counts.get(x["subelement_id"], 0) + 1
    assert counts == {"E1": 68, "E2": 60, "E3": 39, "E4": 63, "E5": 49,
                      "E6": 68, "E7": 99, "E8": 48, "E9": 93, "E0": 12}


def test_exam_weights_sum_to_50(pool):
    assert sum(v[1] for v in pool["subelements"].values()) == 50


def test_errata_text_present_in_body(pool):
    by_id = {x["id"]: x for x in pool["questions"]}
    assert by_id["E6A06"]["choice_b"] == "The change in collector current with respect to the change in base current"
    assert "10 W (+40 dBm)" in by_id["E4D12"]["question"]
    assert by_id["E1D07"]["question"].startswith("Which of the following HF amateur bands")
    assert by_id["E1E10"]["citation"] == "97.509(m)"
    assert by_id["E1E11"]["citation"] == "97.509(i)"
    assert "10 W (+40 dBm)" in by_id["E4D13"]["question"]
    assert by_id["E1F03"]["choice_d"] == ("The amplifier is constructed or modified by an amateur "
                                          "radio operator for use at an amateur station")


def test_multiline_question_and_choice_joined(pool):
    e1a10 = next(x for x in pool["questions"] if x["id"] == "E1A10")
    assert e1a10["question"].endswith("what condition must be met before the station is operated?")
    assert e1a10["choice_b"].endswith("of the ship or aircraft is in use")


def test_figures_detected(pool):
    figs = {x["figure"] for x in pool["questions"] if x["figure"]}
    assert figs == {"E5-1", "E6-1", "E6-2", "E6-3", "E7-1", "E7-2", "E7-3", "E9-1", "E9-2", "E9-3"}
    assert sum(1 for x in pool["questions"] if x["figure"]) == 27


def test_errata_list(pool):
    assert len(pool["errata"]) == 4
    assert "4th Errata" in pool["errata"][0]


def test_gap_in_numbering_rejected():
    broken = MD.replace("E6B04 (A)", "E6B04(A)")  # mangled header -> parser skips it
    with pytest.raises(b.PoolParseError, match="E6B"):
        b.parse_pool(broken)


def test_missing_choice_rejected():
    broken = MD.replace("D. The upper 1 kHz of the signal is outside the 20-meter band", "", 1)
    with pytest.raises(b.PoolParseError, match="E1A01"):
        b.parse_pool(broken)


# --- database ------------------------------------------------------------

def test_db_contents(db):
    conn, _ = db
    assert q(conn, "SELECT COUNT(*) FROM questions WHERE status='active'")[0][0] == 599
    assert q(conn, "SELECT COUNT(*) FROM questions WHERE status='deleted'")[0][0] == 4
    row = q(conn, "SELECT * FROM questions WHERE id='E6A06'")[0]
    assert (row["subelement_id"], row["group_id"], row["correct"]) == ("E6", "E6A", "B")
    assert q(conn, "SELECT title FROM subelements WHERE id='E6'")[0][0] == "Circuit Components"
    assert q(conn, "SELECT title FROM subelements WHERE id='E8'")[0][0] == "Signals and Emissions"
    assert q(conn, "SELECT id FROM subelements ORDER BY sort_order")[-1][0] == "E0"


def add_net(conn, date, status, asked_ids, prepped_ids=()):
    cur = conn.execute("INSERT INTO nets (net_date, ncs, status, created_at) VALUES (?, 'NY4I', ?, 'x')",
                       (date, status))
    rows = [(cur.lastrowid, qid, i, 1) for i, qid in enumerate(asked_ids)]
    rows += [(cur.lastrowid, qid, len(rows) + i, 0) for i, qid in enumerate(prepped_ids)]
    conn.executemany("INSERT INTO net_questions VALUES (?, ?, ?, ?)", rows)
    conn.commit()


def test_usage_counts_only_asked_on_done_nets(db):
    conn, _ = db
    add_net(conn, "2026-09-01", "done", ["E6A01", "E1A01"], prepped_ids=["E7A01"])
    add_net(conn, "2026-09-08", "done", ["E6A01"])
    add_net(conn, "2026-09-15", "prep", ["E6A01", "E3A01"])
    usage = {r["question_id"]: (r["times_asked"], r["last_asked"])
             for r in q(conn, "SELECT * FROM question_usage")}
    assert len(usage) == 603
    assert usage["E6A01"] == (2, "2026-09-08")
    assert usage["E1A01"] == (1, "2026-09-01")
    assert usage["E7A01"] == (0, None)   # prepped, not asked
    assert usage["E3A01"] == (0, None)   # asked flag set, but net not done
    e6 = q(conn, "SELECT * FROM subelement_usage WHERE subelement_id='E6'")[0]
    assert (e6["times_asked"], e6["distinct_asked"], e6["active_questions"]) == (2, 1, 68)
    assert e6["coverage"] == pytest.approx(2 / 68)


def test_net_questions_rejects_unknown_question(db):
    conn, _ = db
    with pytest.raises(sqlite3.IntegrityError):
        add_net(conn, "2026-09-01", "done", ["E6Z99"])


def test_rebuild_preserves_usage_and_retires_removed_questions(pool, db):
    conn, path = db
    add_net(conn, "2026-09-01", "done", ["E1A01", "E1A02"])
    conn.close()

    # Simulate a future errata that deletes E1A02.
    pool2 = dict(pool, questions=[x for x in pool["questions"] if x["id"] != "E1A02"],
                 deleted=pool["deleted"] + ["E1A02"])
    b.write_db(pool2, path, "test.md").close()

    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM net_questions").fetchone()[0] == 2
    assert conn.execute("SELECT status, question FROM questions WHERE id='E1A02'").fetchone()[0] == "deleted"
    assert conn.execute("SELECT question FROM questions WHERE id='E1A02'").fetchone()[0] is not None
    assert conn.execute("SELECT times_asked FROM question_usage WHERE question_id='E1A02'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM questions WHERE status='active'").fetchone()[0] == 598
    conn.close()


def test_rebuild_is_idempotent(pool, db):
    _, path = db
    b.write_db(pool, path, "test.md").close()
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 603
    conn.close()


def test_provenance_recorded(db):
    conn, _ = db
    meta = dict(conn.execute("SELECT key, value FROM pool_meta").fetchall())
    assert meta["license"] == "Public Domain"
    assert "2024-2028 Element 4 Extra Class" in meta["license_statement"]
