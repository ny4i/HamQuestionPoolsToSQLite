# Amateur Question Pool DBs: Design for the Net Control App

Audience: the agent building the net control (NCS) web app. This document defines the
database contract and the behavior the app must implement. The databases are produced by
`build_pool_db.py`. The app does not parse the markdown.

## 1. Purpose

On a weekly radio net, net control reads a few pool questions aloud (question text plus
four choices, then the answer). The app must:

1. Propose a set of questions during a **net prep** step, spread across subelements
   (E1–E9 and E0 for Extra; G1–G9 and G0 for General).
2. Let NCS **override** the proposal: swap, add, remove, reorder, or pick by ID.
3. Show one question at a time in a **read-aloud view**, with the answer hidden until revealed.
4. **Record which questions were actually asked**, so later picks favor unused questions
   and under-covered subelements.

Deployment: one shared web server and several rotating net controls. There is **one database
file per question pool**, and both files use an identical schema.

## 2. Files

| File | Role |
|------|------|
| `2024-2028-Extra-Class-Question-Pool.md` / `.pdf` | Extra (Element 4) source, errata through the 4th (Feb 4, 2026) |
| `2023-2027-General-Class-Question-Pool.md` / `.pdf` | General (Element 3) source, errata through the 6th (Feb 4, 2026) |
| `build_pool_db.py` | Parses and validates a pool markdown file, then creates or updates its database |
| `extra_pool.db` | **Extra** pool database |
| `general_pool.db` | **General** pool database |
| `tests/test_build_pool_db.py` | Extra parsing and errata checks, usage views, rebuild safety |
| `tests/test_general_pool.py` | General parsing and errata checks, plus the guard against writing into another pool's DB |

Build and rebuild (`--db` is required, so a rebuild can never target the wrong file by default):

```
python3 build_pool_db.py --md 2024-2028-Extra-Class-Question-Pool.md   --db extra_pool.db
python3 build_pool_db.py --md 2023-2027-General-Class-Question-Pool.md --db general_pool.db
```

The builder **refuses** to write a pool into a DB whose `pool_meta.pool_name` belongs to a
different pool. Without this guard, a General build run against the Extra DB would mark all
599 Extra questions deleted.

**Copyright:** both pools are public domain. The NCVEC Question Pool Committee released each
one on its pool release page (checked 2026-09-27):

- General: "The NCVEC Question Pool Committee hereby releases into public domain the
  2023-2027 General, Element 3, Question pool."
  https://www.ncvec.org/index.php/2023-2027-general-question-pool-release
- Extra: "The NCVEC Question Pool Committee hereby releases into public domain the
  2024-2028 Element 4 Extra Class Question Pool."
  https://www.ncvec.org/index.php/2024-2028-extra-class-question-pool-release

Each DB carries this information in `pool_meta` under the keys `publisher`, `license`,
`license_statement`, and `source_url`. The app should show a one-line credit (e.g. "Question
pool: NCVEC, public domain", linked to `source_url`) on the read-aloud and browse pages. It
should read these values from `pool_meta` and must not hard-code them. **A future pool gets no
`license` keys until someone checks its release page and adds it to `PROVENANCE` in
`build_pool_db.py`.** The app must treat a missing `license` key as "unknown", not as public
domain.

**Identify a pool by `pool_meta`, not by file name:** `pool_name` (e.g. `2023-2027 General
Class (Element 3)`) and `element` (`3` or `4`).

## 3. Data summary

The ID encodes the hierarchy: `E6A06` means subelement `E6`, group `E6A`, and question 06.
Deleted questions keep their row with `status='deleted'` and NULL text. Errata text changes
are already in the markdown bodies, and the tests check every one of them.

### 3.1 Extra: `extra_pool.db` (expires 2028-06-30)

599 active and 4 deleted (E2A13, E4D05, E6D07, E9E10), with 50 groups. The exam has 50
questions. 27 active questions need a figure (E5-1, E6-1..3, E7-1..3, E9-1..3).

| Subelement | Title | Exam Qs | Active pool Qs |
|---|---|---|---|
| E1 | Commission Rules | 6 | 68 |
| E2 | Operating Procedures | 5 | 60 |
| E3 | Radio Wave Propagation | 3 | 39 |
| E4 | Amateur Practices | 5 | 63 |
| E5 | Electrical Principles | 4 | 49 |
| E6 | Circuit Components | 6 | 68 |
| E7 | Practical Circuits | 8 | 99 |
| E8 | Signals and Emissions | 4 | 48 |
| E9 | Antennas and Transmission Lines | 8 | 93 |
| E0 | Safety | 1 | 12 |

### 3.2 General: `general_pool.db` (expires 2027-06-30)

423 active and 9 deleted (G1A04, G1C08, G1C09, G1C10, G1E09, G6B09, G8C01, G9C06, G9D13),
with 35 groups. The exam has 35 questions. 2 active questions need a figure (G7A12 and
G7A13, both Figure G7-1).

| Subelement | Title | Exam Qs | Active pool Qs |
|---|---|---|---|
| G1 | Commission’s Rules | 5 | 52 |
| G2 | Operating Procedures | 5 | 60 |
| G3 | Radio Wave Propagation | 3 | 37 |
| G4 | Amateur Radio Practices | 5 | 60 |
| G5 | Electrical Principles | 3 | 40 |
| G6 | Circuit Components | 2 | 23 |
| G7 | Practical Circuits | 3 | 38 |
| G8 | Signals and Emissions | 3 | 42 |
| G9 | Antennas and Feed Lines | 4 | 46 |
| G0 | Electrical and RF Safety | 2 | 25 |

Source quirk: G2E02 choice D is printed `D.A DX spotting...` (missing space) in the official
PDF as well. The builder accepts it, and a test covers it.

## 4. Schema

### 4.1 Pool tables: read-only for the app

`build_pool_db.py` owns these tables. **CONSTRAINT: the app must never INSERT, UPDATE,
or DELETE rows in `subelements`, `question_groups`, `questions`, or `pool_meta`.**

```
pool_meta(key PK, value)            -- pool_name, element, schema_version, source_file, built_at, errata_applied,
                                    -- publisher, license, license_statement, source_url (see §2)
subelements(id PK, title, exam_questions, sort_order)      -- sort_order: x1..x9 = 0..8, x0 (safety) = 9
question_groups(id PK, subelement_id FK, title)            -- title = syllabus topic description
questions(id PK, subelement_id FK, group_id FK,
          status 'active'|'deleted',
          question, choice_a, choice_b, choice_c, choice_d,
          correct 'A'..'D', citation, figure)
```

- `citation` holds the FCC Part 97 reference and is filled only for E1/G1 questions. Display it
  with the answer.
- Choice text has no "A. " prefix. The app adds the letter labels.

### 4.2 Usage tables: owned by the app

```
nets(id PK AUTOINCREMENT, net_date 'YYYY-MM-DD', ncs (uppercase callsign),
     status 'prep'|'done', notes, created_at ISO-UTC, completed_at ISO-UTC)
net_questions(net_id FK -> nets ON DELETE CASCADE,
              question_id FK -> questions,
              position INT, asked 0|1,
              PK(net_id, question_id))
```

The builder creates these tables with `CREATE TABLE IF NOT EXISTS` and never writes to them.

### 4.3 Views (read these for stats and selection)

```
question_usage(question_id, subelement_id, group_id, status, figure, times_asked, last_asked)
subelement_usage(subelement_id, title, exam_questions, sort_order,
                 active_questions, times_asked, distinct_asked, last_asked, coverage)
```

**Usage rule (hard):** a question counts as used only when `net_questions.asked = 1` **and**
`nets.status = 'done'`. Prepped questions that NCS never asked do not count. The views
already apply this rule, so the app must not recompute usage any other way.

`coverage = times_asked / active_questions`. It is the balancing metric in §5.

## 5. Selection algorithm (net prep)

Input: `n` (default 3, configurable), `allow_figures` (default false), `exclude` (IDs already
on this net).

```
eligible(q) = q.status = 'active'
              AND q.id NOT IN exclude
              AND (allow_figures OR q.figure IS NULL)

used_subs = {}
REPEAT n times:
    subs = subelements having >= 1 eligible question
    IF subs is empty: STOP (return fewer than n)
    fresh = subs - used_subs; IF fresh is empty: fresh = subs
    sid = argmin over fresh of (coverage, last_asked NULLS FIRST, random)
    q   = argmin over eligible questions in sid of
            (times_asked, group_times_asked, last_asked NULLS FIRST, random)
    add q to result; exclude += q.id; used_subs += sid
```

Rationale:
- **Distinct subelements per net** meets the "different areas" requirement.
- **Coverage, not raw count**, picks the subelement. With raw counts, E0 (12 questions) would
  come up as often as E7 (99 questions), and its questions would be used up and repeated
  within a few months. Coverage keeps every subelement moving through its questions at the
  same rate.
- **Never-asked questions come first** within a subelement. No repeats happen until the
  subelement's eligible questions are exhausted.
- **`group_times_asked`** (sum of `times_asked` over the question's group) spreads picks
  across topics inside a subelement.
- **Figure questions are excluded by default.** A schematic or Smith chart cannot be read over
  the air. NCS can still add one by ID.

`random` is a tie-breaker only. For deterministic tests, accept an injected RNG seed.

## 6. Workflows the app must support

| Step | DB effect |
|------|-----------|
| Create net (date, NCS call) | INSERT `nets` with status='prep'. INSERT `n` `net_questions` rows from §5 with asked=0 and positions 0..n-1 |
| Swap a question | UPDATE that row's `question_id` to a pick from §5. Default to the same subelement, with "any subelement" as an option. `exclude` = all IDs on the net |
| Pick by ID | Validate: the ID exists, `status='active'`, and it is not already on the net. Show the question's `times_asked` and `last_asked` before confirming |
| Add / remove / reorder | INSERT / DELETE / renumber `position` values |
| Browse | List by subelement → group, with `times_asked` and `last_asked` from `question_usage`, and an "add to net" action |
| Read-aloud view | One question per screen in large text: ID, subelement title, question, and choices A–D. **Answer hidden until NCS clicks Reveal**, then show the letter, the text, and the citation. Buttons: "Asked → next" (sets asked=1) and "Skip → next" (leaves asked=0) |
| Complete net | Confirmation screen with a checkbox per question, prefilled from `asked`, so NCS can correct it. On submit: set `asked`, status='done', completed_at=now, all in **one transaction** |
| Reopen net | status='prep' and completed_at=NULL, to correct mistakes. Usage drops back out until the net is completed again |
| Delete net | Allowed only when status='prep'. Deleting a done net would silently erase history |
| Stats | `subelement_usage` ordered by `sort_order`: times asked, distinct asked vs. active, last asked |

Multiple nets can be in 'prep' at once (for example, next week's net prepped early). When
picking for a prep net, **do not** exclude questions on other prep nets. They are not used yet.
Optionally, warn when a question sits on two open nets.

## 7. Known gaps and decisions for the app

1. **Figures are not in the DB.** The diagrams are 10 in Extra and just G7-1 in General. The
   default policy excludes figure questions, so this does not block v1. NCVEC publishes the
   figures separately on each release page: for General, `G7-1.pdf` and a JPG; for Extra,
   `Extra_Figures_2024-2028-1.pdf`, three diagram-page JPGs, and `e4_2024-svgs.zip`, which
   has SVGs that stay sharp at any size and are the best choice for a web page. If you add
   figures, serve them as static files named by the `figure` column (e.g.
   `static/figures/E5-1.svg`). Do not add BLOBs to the pool tables.
2. **Syllabus counts in the source are inconsistent.** E6's stated 68 reflects its deletion,
   but E2/E4/E9 do not. General's G1 count (54) was updated through the 4th errata but not the
   6th (it is currently 52 active). The builder therefore validates on contiguous per-group
   numbering (active + deleted = 01..N) instead. Do not "fix" counts in the app.
3. **Pool expiry. General: June 30, 2027, nine months from now. Extra: June 30, 2028.** Each
   successor pool reuses the ID scheme (G1A01 and so on) with different questions. Build every
   successor into a **new** DB file, never into an old one. The builder's pool-name guard
   blocks the obvious mistake. The app must let the operator switch the active DB for a pool
   level without code changes, e.g. with a config entry per pool.
4. **Authentication.** This is a shared server with endpoints that change state. At minimum,
   use a shared NCS password (HTTP basic auth or a session login) plus CSRF protection on
   POSTs. Record the NCS call on each net for accountability.
5. **Multiple pools (decision the app must make explicit).** Each net draws from exactly one
   pool DB, and `nets`/`net_questions` live in that DB, so usage history stays per pool. The
   app needs a pool selector at net creation, with Extra and General listed from config.
   If the net ever wants one General and one Extra question in the same session, model it
   as two nets on the same date, one per DB. Do not ATTACH the databases and join across
   them, because the `questions.id` foreign key cannot span files.

## 8. Operational constraints

- **SQLite on a shared server:** set `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`
  (per connection, since it is off by default), and `PRAGMA busy_timeout=5000`. A weekly net
  with a handful of NCS users is far below SQLite's limits. Do not move to a server DB
  without a measured need.
- **Backups:** each pool DB holds the only copy of its usage history. Back up **both**, e.g.
  `sqlite3 general_pool.db ".backup general-YYYYMMDD.db"`, not `cp`, because WAL makes a
  plain file copy unsafe while the app is running. Back up before every rebuild or deploy.
- **Checking for new errata:** each pool's release page (`source_url` in `pool_meta`) lists
  the errata, newest first, e.g. "6th Errata Issued February 4, 2026". Compare it with the
  first entry of `pool_meta.errata_applied`. As of 2026-09-27 both DBs are current (General
  6th errata and Extra 4th errata, both issued February 4, 2026). If they differ, download
  the new release, convert it to markdown, and rebuild.
- **Rebuilding after new errata:** stop the app or accept a brief lock, back up, then run
  `build_pool_db.py --md <that pool's .md> --db <that pool's live db>`. The builder upserts pool rows, marks questions missing
  from the markdown as deleted, and recreates the views. It never touches `nets` or
  `net_questions`. The tests verify this.

## 9. Acceptance tests the app must have

1. Usage: a prepped but unasked question has `times_asked = 0`, and a question asked on a prep
   net has `times_asked = 0` until that net is completed.
2. Selection with n=3 on an empty history returns 3 distinct subelements and no figure
   questions.
3. Selection never returns a question already on the net, or a deleted one.
4. After E0's 12 questions are each asked once, the next E0 pick is a repeat (the least
   recently asked). Before that, no E0 repeats.
5. Coverage balancing: with E7 at 1 ask (1/99) and E0 at 1 ask (1/12), E7 is preferred.
6. Complete net is atomic: a simulated failure mid-transaction leaves status='prep' and the
   `asked` flags unchanged.
7. Pick by ID rejects unknown, deleted, and duplicate IDs, and it rejects an ID from the other
   pool (e.g. `G1A01` on an Extra net).
8. Deleting a done net is refused.
9. The app never writes the pool tables. Check this by grepping the app code for
   INSERT/UPDATE/DELETE against `questions|subelements|question_groups|pool_meta`.
