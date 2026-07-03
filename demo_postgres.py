"""
demo_postgres.py — Runs the FULL AutoFixSQL pipeline (execution_monitor
-> error_diagnosis -> repair_engine -> retry_controller) against your
real Postgres/Spider database. This is the script to use for the live
class demo.

Edit DEMO_QUERIES below with real table/column names from your Spider
schema (or a table you know exists), each intentionally broken in a
different way, so the walkthrough shows each repair rule firing.

Run: python -m demo.demo_postgres
(Set PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD env vars first if your
 setup differs from src/config.py defaults.)
"""

import sys, os, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.pipeline import autofix

# TODO: replace with real broken queries against your loaded schema.
# Each should map to one of the 4 diagnosis categories / 6 repair rules.
DEMO_QUERIES = [
    "SELECT * FROM studnts",                              # missing_table -> table substitution + SELECT * expansion
    "SELECT nam FROM students",                            # missing_column -> column substitution
    "SELECT * FROM students, enrollments",                 # join_error -> FK-based JOIN inference
    "SELECT * FROM students WHERE id = '5'",               # type_mismatch -> type cast/coercion
]


def main():
    for i, sql in enumerate(DEMO_QUERIES, start=1):
        print(f"\n=== Demo query {i} ===")
        print(f"Original: {sql}")
        output = autofix(sql)
        print(f"Success:  {output['success']}")
        print(f"Final SQL: {output['final_sql']}")
        print(f"Attempts:  {output['attempts']}")
        if output["safe_failure_message"]:
            print(f"Safe failure: {output['safe_failure_message']}")
        print("Repair trail:")
        print(json.dumps(output["repair_trail"], indent=2, default=str))


if __name__ == "__main__":
    main()
