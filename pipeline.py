"""
pipeline.py — End-to-end AutoFixSQL entry point.

Usage:
    python -m src.pipeline "SELECT * FROM studnts WHERE id = '5'"

Wires together: schema_extractor -> retry_controller
(execution_monitor -> error_diagnosis -> repair_engine, looped).
"""

import argparse
import json

from src.schema_extractor import extract_schema, get_connection
from src.retry_controller import run_with_repair


def autofix(sql: str, conn=None) -> dict:
    conn = conn or get_connection()
    schema = extract_schema(conn=conn)
    pipeline_result = run_with_repair(sql, schema, conn=conn)

    return {
        "original_sql": sql,
        "success": pipeline_result.success,
        "final_sql": pipeline_result.final_sql,
        "rows": pipeline_result.result.rows if pipeline_result.result and pipeline_result.result.success else None,
        "columns": pipeline_result.result.columns if pipeline_result.result and pipeline_result.result.success else None,
        "attempts": len(pipeline_result.attempts),
        "repair_trail": [
            {
                "attempt": a.attempt_number,
                "sql_tried": a.sql_tried,
                "error": a.result.error_message if not a.result.success else None,
                "diagnosis_category": a.diagnosis.category if a.diagnosis else None,
                "repaired_sql": a.repaired_sql,
            }
            for a in pipeline_result.attempts
        ],
        "safe_failure_message": pipeline_result.safe_failure_message,
    }


def main():
    parser = argparse.ArgumentParser(description="AutoFixSQL: auto-repair a failing SQL query.")
    parser.add_argument("sql", help="The SQL query to execute (and auto-repair if it fails).")
    args = parser.parse_args()

    output = autofix(args.sql)
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
