#!/usr/bin/env python3
"""Convert an NCVEC amateur question pool markdown (Element 3 General, Element 4 Extra) into SQLite.

Usage:
    python3 build_pool_db.py --md 2024-2028-Extra-Class-Question-Pool.md --db extra_pool.db
    python3 build_pool_db.py --md 2023-2027-General-Class-Question-Pool.md --db general_pool.db

One database per pool. Safe to re-run against the same pool (e.g. after new
errata): pool tables are upserted, questions no longer in the markdown are
marked 'deleted', and the usage tables (nets, net_questions) are never
modified. Refuses to write a pool into a database built from a different pool.
See DESIGN.md.
"""
import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1"

SYLLABUS_RE = re.compile(r"^FCC Element (\d) Question Pool Syllabus$")
BODY_START_RE = re.compile(r"^FCC Element (\d) Question Pool$")
BODY_END = "~~~end of question pool text~~~"

DASH = r"[-–]"
SUBELEMENT_RE = re.compile(rf"^SUBELEMENT ([A-Z]\d) {DASH} (.+?) (?:{DASH} ?)?\[(\d+) exam questions?.*?\]\s*(\d+) Questions",
                           re.IGNORECASE)
GROUP_RE = re.compile(rf"^([A-Z]\d[A-Z])(?: {DASH})? (.+)")
QUESTION_RE = re.compile(r"^([A-Z]\d[A-Z]\d{2}) \(([A-D])\)\s*(?:\[(.*)\])?\s*$")
DELETED_RE = re.compile(r"^([A-Z]\d[A-Z]\d{2})\s+Question Deleted")
CHOICE_RE = re.compile(r"^([A-D])\. (.*)")
TIGHT_CHOICE_RE = re.compile(r"^([A-D])\.([A-Z].*)")   # missing space; only accepted as the next expected letter
FIGURE_RE = re.compile(r"Figure ([A-Z]\d-\d+)")
ERRATA_RE = re.compile(r"^(.*Errata)\s*$")
ISSUED_RE = re.compile(r"^Issued (.+)$")
# Copyright status, keyed by pool_name. Statements quoted verbatim from each pool's release
# page on ncvec.org (verified 2026-09-27). A pool not listed here gets no license keys:
# never assume public domain for a new pool without checking its release page.
PROVENANCE = {
    "2023-2027 General Class (Element 3)": {
        "license": "Public Domain",
        "license_statement": "The NCVEC Question Pool Committee hereby releases into public domain "
                             "the 2023-2027 General, Element 3, Question pool.",
        "source_url": "https://www.ncvec.org/index.php/2023-2027-general-question-pool-release",
    },
    "2024-2028 Extra Class (Element 4)": {
        "license": "Public Domain",
        "license_statement": "The NCVEC Question Pool Committee hereby releases into public domain "
                             "the 2024-2028 Element 4 Extra Class Question Pool.",
        "source_url": "https://www.ncvec.org/index.php/2024-2028-extra-class-question-pool-release",
    },
}
ACRONYMS = {"RF"}
SMALL_WORDS = {"and", "of", "the"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS pool_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subelements (
    id             TEXT PRIMARY KEY,               -- 'E6'
    title          TEXT NOT NULL,                  -- 'Circuit Components'
    exam_questions INTEGER NOT NULL,               -- questions from this subelement on a real exam
    sort_order     INTEGER NOT NULL                -- pool order: E1..E9 then E0
);
CREATE TABLE IF NOT EXISTS question_groups (
    id            TEXT PRIMARY KEY,                -- 'E6A'
    subelement_id TEXT NOT NULL REFERENCES subelements(id),
    title         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
    id            TEXT PRIMARY KEY,                -- 'E6A06'
    subelement_id TEXT NOT NULL REFERENCES subelements(id),
    group_id      TEXT NOT NULL REFERENCES question_groups(id),
    status        TEXT NOT NULL CHECK (status IN ('active', 'deleted')),
    question      TEXT,
    choice_a      TEXT,
    choice_b      TEXT,
    choice_c      TEXT,
    choice_d      TEXT,
    correct       TEXT CHECK (correct IN ('A', 'B', 'C', 'D')),
    citation      TEXT,                            -- FCC rule reference, E1 only
    figure        TEXT,                            -- 'E5-1' if the question needs a diagram
    CHECK (status = 'deleted' OR (question IS NOT NULL AND correct IS NOT NULL
           AND choice_a IS NOT NULL AND choice_b IS NOT NULL
           AND choice_c IS NOT NULL AND choice_d IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_questions_subelement ON questions(subelement_id, status);

-- Usage tracking: owned by the net control app, never touched by this script.
CREATE TABLE IF NOT EXISTS nets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    net_date     TEXT NOT NULL,                    -- ISO date 'YYYY-MM-DD'
    ncs          TEXT NOT NULL,                    -- net control callsign, uppercase
    status       TEXT NOT NULL DEFAULT 'prep' CHECK (status IN ('prep', 'done')),
    notes        TEXT,
    created_at   TEXT NOT NULL,                    -- ISO-8601 UTC
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS net_questions (
    net_id      INTEGER NOT NULL REFERENCES nets(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id),
    position    INTEGER NOT NULL,
    asked       INTEGER NOT NULL DEFAULT 0 CHECK (asked IN (0, 1)),
    PRIMARY KEY (net_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_net_questions_question ON net_questions(question_id);

"""

# Views are derived, so they are dropped and recreated on every build.
VIEWS = """
DROP VIEW IF EXISTS subelement_usage;
DROP VIEW IF EXISTS question_usage;

-- A question is "used" only if asked = 1 on a net with status 'done'.
CREATE VIEW question_usage AS
SELECT q.id AS question_id, q.subelement_id, q.group_id, q.status, q.figure,
       COUNT(h.net_date) AS times_asked,
       MAX(h.net_date)   AS last_asked
FROM questions q
LEFT JOIN (SELECT nq.question_id, n.net_date
           FROM net_questions nq JOIN nets n ON n.id = nq.net_id
           WHERE nq.asked = 1 AND n.status = 'done') h ON h.question_id = q.id
GROUP BY q.id;

CREATE VIEW subelement_usage AS
SELECT s.id AS subelement_id, s.title, s.exam_questions, s.sort_order,
       SUM(u.status = 'active')                       AS active_questions,
       SUM(u.times_asked)                             AS times_asked,
       SUM(u.status = 'active' AND u.times_asked > 0) AS distinct_asked,
       MAX(u.last_asked)                              AS last_asked,
       CAST(SUM(u.times_asked) AS REAL) / SUM(u.status = 'active') AS coverage
FROM subelements s JOIN question_usage u ON u.subelement_id = s.id
GROUP BY s.id;
"""


class PoolParseError(Exception):
    pass


def title_case(s: str) -> str:
    """'ELECTRICAL AND RF SAFETY' -> 'Electrical and RF Safety'; handles 'COMMISSION’S'."""
    words = s.split()
    return " ".join(w if w in ACRONYMS else
                    w.lower() if i and w.lower() in SMALL_WORDS else
                    w[:1] + w[1:].lower()
                    for i, w in enumerate(words))


def parse_toc(lines):
    """Parse the syllabus section (already sliced out) into
    {sid: (title, exam_questions, sort_order)} and {group_id: title}."""
    subelements, groups = {}, {}
    current = None
    for line in lines:
        m = SUBELEMENT_RE.match(line)
        if m:
            subelements[m.group(1)] = (title_case(m.group(2).strip()), int(m.group(3)), len(subelements))
            current = None
            continue
        m = GROUP_RE.match(line)
        if m and subelements:
            current = m.group(1)
            groups[current] = m.group(2).strip()
        elif current and line.strip():
            groups[current] += " " + line.strip()
        else:
            current = None
    return subelements, groups


def parse_errata(lines):
    """Return 'Name (issued date)' for each errata notice in the preamble (already sliced out)."""
    found = []
    for i, line in enumerate(lines):
        m = ERRATA_RE.match(line.strip())
        if m and i + 1 < len(lines) and (d := ISSUED_RE.match(lines[i + 1].strip())):
            found.append(f"{m.group(1)} (issued {d.group(1)})")
    return found


def parse_body(lines):
    questions, deleted = [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        if m := DELETED_RE.match(line):
            deleted.append(m.group(1))
            i += 1
            continue
        m = QUESTION_RE.match(line)
        if not m:
            i += 1
            continue
        qid, correct, citation = m.group(1), m.group(2), m.group(3)
        i += 1
        text, choices, current = [], {}, None
        while i < len(lines) and lines[i].strip() != "~~":
            ln = lines[i].strip()
            cm = CHOICE_RE.match(ln)
            expected = "ABCD"[len(choices)] if len(choices) < 4 else None
            if not cm and expected and (tm := TIGHT_CHOICE_RE.match(ln)) and tm.group(1) == expected:
                cm = tm   # source typo 'D.A DX spotting...' (G2E02, also in the official PDF)
            if cm:
                current = cm.group(1)
                choices[current] = cm.group(2)
            elif ln:
                if current:
                    choices[current] += " " + ln
                else:
                    text.append(ln)
            i += 1
        question = " ".join(text)
        if sorted(choices) != ["A", "B", "C", "D"] or not question:
            raise PoolParseError(f"Malformed question {qid}: choices={sorted(choices)} text={question!r}")
        fig = FIGURE_RE.search(question + " " + " ".join(choices.values()))
        questions.append({
            "id": qid, "subelement_id": qid[:2], "group_id": qid[:3], "correct": correct,
            "citation": citation, "question": question,
            "choice_a": choices["A"], "choice_b": choices["B"],
            "choice_c": choices["C"], "choice_d": choices["D"],
            "figure": fig.group(1) if fig else None,
        })
    return questions, deleted


def parse_pool(md_text: str) -> dict:
    """Layout: errata preamble | '<years> <Class> Class' + 'FCC Element N Question Pool Syllabus'
    | '<years> <Class> Class' + 'FCC Element N Question Pool' + questions | end marker."""
    lines = [l.strip() for l in md_text.splitlines()]
    try:
        syllabus = next(i for i, l in enumerate(lines) if SYLLABUS_RE.match(l))
        start = next(i for i, l in enumerate(lines) if BODY_START_RE.match(l))
        end = next(i for i, l in enumerate(lines) if l == BODY_END)
    except StopIteration:
        raise PoolParseError("Could not find syllabus / pool body / end-of-pool markers")
    if not syllabus < start < end:
        raise PoolParseError("Pool markers out of order")
    element = BODY_START_RE.match(lines[start]).group(1)
    pool_name = f"{lines[start - 1]} (Element {element})"   # e.g. '2023-2027 General Class (Element 3)'

    subelements, groups = parse_toc(lines[syllabus:start])
    questions, deleted = parse_body(lines[start:end])
    validate(subelements, groups, questions, deleted)
    return {"pool_name": pool_name, "element": element, "subelements": subelements, "groups": groups,
            "questions": questions, "deleted": deleted, "errata": parse_errata(lines[:syllabus])}


def validate(subelements, groups, questions, deleted):
    ids = [q["id"] for q in questions]
    errors = []
    if len(ids) + len(deleted) != len(set(ids) | set(deleted)):
        errors.append("Duplicate question ids")
    # Within each group, active + deleted numbers must run 01..N with no gaps.
    # A gap means a question header was mangled in the PDF-to-markdown conversion.
    numbers = {}
    for qid in ids + deleted:
        numbers.setdefault(qid[:3], []).append(int(qid[3:]))
    for group, nums in sorted(numbers.items()):
        if sorted(nums) != list(range(1, max(nums) + 1)):
            errors.append(f"{group}: non-contiguous numbering {sorted(nums)}")
    if missing := set(numbers) - groups.keys():
        errors.append(f"Groups without syllabus titles: {sorted(missing)}")
    if missing := {g[:2] for g in groups} - subelements.keys():
        errors.append(f"Subelements without syllabus entries: {sorted(missing)}")
    if errors:
        raise PoolParseError("Validation failed:\n  " + "\n  ".join(errors))


class WrongPoolError(Exception):
    pass


def write_db(pool: dict, db_path: Path, source_name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    # Guard: writing General into the Extra DB would mark every Extra question deleted.
    has_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pool_meta'").fetchone()
    if has_meta:
        row = conn.execute("SELECT value FROM pool_meta WHERE key='pool_name'").fetchone()
        if row and row[0] != pool["pool_name"]:
            conn.close()
            raise WrongPoolError(f"{db_path} holds '{row[0]}', refusing to write '{pool['pool_name']}'")
    with conn:
        conn.executescript(SCHEMA)
        conn.executescript(VIEWS)
        conn.executemany(
            "INSERT INTO subelements (id, title, exam_questions, sort_order) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, exam_questions=excluded.exam_questions, "
            "sort_order=excluded.sort_order",
            [(sid, *v) for sid, v in pool["subelements"].items()])
        conn.executemany(
            "INSERT INTO question_groups (id, subelement_id, title) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title",
            [(gid, gid[:2], title) for gid, title in pool["groups"].items()])
        cols = ["id", "subelement_id", "group_id", "question", "choice_a", "choice_b",
                "choice_c", "choice_d", "correct", "citation", "figure"]
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols[1:])
        conn.executemany(
            f"INSERT INTO questions ({', '.join(cols)}, status) VALUES ({', '.join('?' * len(cols))}, 'active') "
            f"ON CONFLICT(id) DO UPDATE SET {updates}, status='active'",
            [tuple(q[c] for c in cols) for q in pool["questions"]])
        # Deleted questions keep their row (and any text they had) so usage history stays valid.
        conn.executemany(
            "INSERT INTO questions (id, subelement_id, group_id, status) VALUES (?, ?, ?, 'deleted') "
            "ON CONFLICT(id) DO UPDATE SET status='deleted'",
            [(d, d[:2], d[:3]) for d in pool["deleted"]])
        active = [q["id"] for q in pool["questions"]]
        conn.execute(f"UPDATE questions SET status='deleted' WHERE id NOT IN ({','.join('?' * len(active))})",
                     active)
        meta = {
            "pool_name": pool["pool_name"],
            "element": pool["element"],
            "schema_version": SCHEMA_VERSION,
            "source_file": source_name,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "errata_applied": "; ".join(pool["errata"]),
            "publisher": "NCVEC Question Pool Committee",
            **PROVENANCE.get(pool["pool_name"], {}),
        }
        conn.execute("DELETE FROM pool_meta WHERE key IN ('license', 'license_statement', 'source_url')")
        conn.executemany("INSERT OR REPLACE INTO pool_meta (key, value) VALUES (?, ?)", meta.items())
    return conn


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--md", type=Path, required=True, help="pool markdown file")
    ap.add_argument("--db", type=Path, required=True, help="SQLite file to create or update")
    args = ap.parse_args(argv)
    try:
        pool = parse_pool(args.md.read_text(encoding="utf-8"))
        conn = write_db(pool, args.db, args.md.name)
    except (PoolParseError, WrongPoolError) as e:
        sys.exit(str(e))
    active, deleted, figs = conn.execute(
        "SELECT SUM(status='active'), SUM(status='deleted'), SUM(status='active' AND figure IS NOT NULL) "
        "FROM questions").fetchone()
    conn.close()
    print(f"{args.db}: {pool['pool_name']}: {active} active, {deleted} deleted, {figs} active questions need a figure")


if __name__ == "__main__":
    main()
