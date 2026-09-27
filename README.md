# Ham Question Pools to SQLite

Converts the NCVEC amateur radio question pools (markdown text taken from the official PDFs)
into SQLite databases. A net control app uses these to pick, read aloud, and track pool
questions on a weekly net.

| Pool | Source | Database | Active / deleted |
|------|--------|----------|------------------|
| 2023-2027 General (Element 3) | `2023-2027-General-Class-Question-Pool.md`, through the 6th errata | `general_pool.db` | 423 / 9 |
| 2024-2028 Extra (Element 4) | `2024-2028-Extra-Class-Question-Pool.md`, through the 4th errata | `extra_pool.db` | 599 / 4 |

Both pools are public domain, released by the NCVEC Question Pool Committee. See `DESIGN.md` §2.

## Build

```
python3 build_pool_db.py --md 2024-2028-Extra-Class-Question-Pool.md   --db extra_pool.db
python3 build_pool_db.py --md 2023-2027-General-Class-Question-Pool.md --db general_pool.db
python3 -m pytest tests
```

Requires Python 3.10+ and uses only the standard library. Running pytest also needs pytest
installed.

You can re-run the build against a live database after new errata. It updates the questions,
marks withdrawn questions as deleted, and never touches the usage tables. It refuses to write
one pool into another pool's database.

## Design

`DESIGN.md` is the contract for the net control app. It covers the schema, when a question
counts as used, the selection algorithm, the workflows, operations, and the acceptance tests.
