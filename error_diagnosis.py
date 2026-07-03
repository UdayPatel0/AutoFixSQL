"""
error_diagnosis.py — Classifies a failed SQL query into one of four
error categories using the SQLSTATE code + schema metadata, and
suggests the most likely correction using difflib string similarity.

Categories: missing_table | missing_column | join_error | type_mismatch
"""

import difflib
import re
from dataclasses import dataclass, field
from typing import Optional

import sqlglot
from sqlglot import exp

from src.config import NAME_SIMILARITY_THRESHOLD
from src.execution_monitor import ExecutionResult, classify_sqlstate


@dataclass
class Diagnosis:
    category: str                      # missing_table | missing_column | join_error | type_mismatch | unknown
    bad_identifier: Optional[str] = None
    suggested_identifier: Optional[str] = None
    table_hint: Optional[str] = None   # table the bad column was referenced on, if known
    details: str = ""
    schema_snapshot: dict = field(default_factory=dict, repr=False)


def _extract_identifier(message: str) -> Optional[str]:
    """
    Pull the quoted identifier out of a Postgres error message, e.g.
    'relation "studnts" does not exist' -> 'studnts'
    'column "nam" does not exist'       -> 'nam'
    """
    match = re.search(r'"([^"]+)"', message)
    return match.group(1) if match else None


def _best_match(name: str, candidates: list[str]) -> Optional[str]:
    if not candidates:
        return None
    matches = difflib.get_close_matches(
        name, candidates, n=1, cutoff=NAME_SIMILARITY_THRESHOLD
    )
    return matches[0] if matches else None


def _referenced_tables(sql: str) -> list[str]:
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
        return [t.name for t in tree.find_all(exp.Table)]
    except Exception:
        # SQL too malformed to parse (e.g. genuine syntax error) -> fall back
        # to a regex scan of the FROM/JOIN clause so join-error detection
        # still works even when sqlglot can't build a tree.
        match = re.search(r"\bFROM\s+(.+?)(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|$)",
                           sql, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        from_clause = match.group(1)
        # split on commas and JOIN keywords, strip aliases
        parts = re.split(r",|\bJOIN\b", from_clause, flags=re.IGNORECASE)
        tables = []
        for p in parts:
            tok = p.strip().split()
            if tok:
                tables.append(tok[0])
        return tables


def diagnose(result: ExecutionResult, schema: dict) -> Diagnosis:
    """
    Given a failed ExecutionResult and the current schema dict
    (from schema_extractor.extract_schema), classify the failure
    and suggest a fix target.
    """
    if result.success:
        raise ValueError("diagnose() called on a successful ExecutionResult")

    kind = classify_sqlstate(result.sqlstate)
    bad_id = _extract_identifier(result.error_message or "")
    table_names = list(schema.get("tables", {}).keys())

    # --- Missing table ---
    if kind == "undefined_table":
        suggestion = _best_match(bad_id, table_names) if bad_id else None
        return Diagnosis(
            category="missing_table",
            bad_identifier=bad_id,
            suggested_identifier=suggestion,
            details=f"Referenced table '{bad_id}' not found in schema.",
            schema_snapshot=schema,
        )

    # --- Missing column ---
    if kind == "undefined_column":
        ref_tables = _referenced_tables(result.sql)
        # Search columns across all referenced tables (or all tables if none parsed)
        candidate_tables = ref_tables or table_names
        best_table, best_col, best_score = None, None, 0.0
        for t in candidate_tables:
            cols = list(schema.get("tables", {}).get(t, {}).get("columns", {}).keys())
            match = _best_match(bad_id, cols) if bad_id else None
            if match:
                score = difflib.SequenceMatcher(None, bad_id, match).ratio()
                if score > best_score:
                    best_table, best_col, best_score = t, match, score
        return Diagnosis(
            category="missing_column",
            bad_identifier=bad_id,
            suggested_identifier=best_col,
            table_hint=best_table,
            details=f"Referenced column '{bad_id}' not found on {candidate_tables}.",
            schema_snapshot=schema,
        )

    # --- Type mismatch (undefined_function often == "operator does not exist: text = integer") ---
    if kind in ("undefined_function", "not_null_violation"):
        return Diagnosis(
            category="type_mismatch",
            details=result.error_message,
            schema_snapshot=schema,
        )

    # --- Syntax errors that stem from a bad/missing join are classified as join_error
    #     when the query references 2+ tables with no shared FK path.
    if kind == "syntax_error":
        ref_tables = _referenced_tables(result.sql)
        if len(ref_tables) >= 2:
            return Diagnosis(
                category="join_error",
                details=f"Syntax/join issue across tables {ref_tables}: {result.error_message}",
                schema_snapshot=schema,
            )

    return Diagnosis(
        category="unknown",
        details=result.error_message or "Unclassified error.",
        schema_snapshot=schema,
    )
