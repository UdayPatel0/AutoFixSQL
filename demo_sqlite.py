"""
demo_sqlite.py — A quick, dependency-light way to SEE the AutoFixSQL
pipeline work end-to-end, using an in-memory SQLite DB instead of your
real Postgres/Spider instance. This is just for demonstration/sanity
checking the repair logic in isolation; your actual grading demo
should run against Postgres (see demo/demo_postgres.py + README).

Run: python demo/demo_sqlite.py
"""

import sqlite3
import difflib
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.error_diagnosis import Diagnosis
from src.repair_engine import repair_missing_table, repair_select_star

# --- tiny demo schema + data ---
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT)")
conn.execute("INSERT INTO students VALUES (1, 'Alice'), (2, 'Bob')")
conn.commit()

SCHEMA = {
    "tables": {"students": {"columns": {"id": "integer", "name": "text"}, "primary_key": ["id"]}},
    "foreign_keys": [],
}


def try_run(sql):
    try:
        cur = conn.execute(sql)
        return True, cur.fetchall(), None
    except sqlite3.Error as e:
        return False, None, str(e)


def main():
    bad_sql = "SELECT * FROM studnts"   # typo'd table name
    print(f"Attempt 1 (original): {bad_sql}")
    ok, rows, err = try_run(bad_sql)

    if not ok:
        print(f"  FAILED: {err}")
        # Manual diagnosis (SQLite error text differs from Postgres SQLSTATE,
        # so we short-circuit straight to the repair rule for this demo)
        table_names = list(SCHEMA["tables"].keys())
        suggestion = difflib.get_close_matches("studnts", table_names, n=1, cutoff=0.5)
        suggestion = suggestion[0] if suggestion else None
        diag = Diagnosis(category="missing_table", bad_identifier="studnts", suggested_identifier=suggestion)

        repaired_sql = repair_missing_table(bad_sql, diag)
        repaired_sql = repair_select_star(repaired_sql, SCHEMA) or repaired_sql
        print(f"Attempt 2 (repaired): {repaired_sql}")

        ok, rows, err = try_run(repaired_sql)
        if ok:
            print(f"  SUCCESS: {rows}")
        else:
            print(f"  STILL FAILED: {err}")


if __name__ == "__main__":
    main()
