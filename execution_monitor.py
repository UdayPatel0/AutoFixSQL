"""
execution_monitor.py — Executes SQL against Postgres and captures
structured diagnostic output on failure (SQLSTATE code, message, etc.)
for use by error_diagnosis.py.
"""

from dataclasses import dataclass, field
from typing import Optional, Any
import psycopg2

from src.config import DBConfig
from src.schema_extractor import get_connection


@dataclass
class ExecutionResult:
    success: bool
    sql: str
    rows: Optional[list] = None
    columns: Optional[list] = None
    sqlstate: Optional[str] = None
    error_message: Optional[str] = None
    raw_exception: Optional[Any] = field(default=None, repr=False)


def run_query(sql: str, conn=None, db_config: DBConfig = None) -> ExecutionResult:
    """
    Execute `sql`. On success, return rows + column names.
    On failure, roll back and return structured error info
    (SQLSTATE code + message) instead of raising.
    """
    own_conn = conn is None
    conn = conn or get_connection(db_config)

    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            if cur.description is not None:
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
            else:
                columns, rows = [], []
            conn.commit()
            return ExecutionResult(success=True, sql=sql, rows=rows, columns=columns)

    except psycopg2.Error as e:
        conn.rollback()
        sqlstate = e.pgcode  # e.g. '42P01' undefined_table, '42703' undefined_column
        message = e.pgerror.strip() if e.pgerror else str(e)
        return ExecutionResult(
            success=False,
            sql=sql,
            sqlstate=sqlstate,
            error_message=message,
            raw_exception=e,
        )
    finally:
        if own_conn:
            conn.close()


# Reference table of SQLSTATE codes AutoFixSQL knows how to reason about.
# (Matches the 5 codes covered by the Week 3 unit test suite.)
KNOWN_SQLSTATES = {
    "42P01": "undefined_table",     # missing table
    "42703": "undefined_column",    # missing column
    "42883": "undefined_function",  # e.g. bad operator/type combo
    "23502": "not_null_violation",  # required column missing/null
    "42601": "syntax_error",        # malformed SQL
}


def classify_sqlstate(sqlstate: str) -> str:
    return KNOWN_SQLSTATES.get(sqlstate, "unknown_error")
