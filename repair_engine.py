"""
repair_engine.py — Applies one of 6 repair rules to a failed SQL query
based on the Diagnosis produced by error_diagnosis.py:

  1. Table name substitution        (missing_table)
  2. Column name substitution       (missing_column)
  3. FK-based JOIN inference        (join_error)
  4. Type cast insertion            (type_mismatch)
  5. Alias conflict resolution      (duplicate/clashing aliases)
  6. SELECT * expansion             (SELECT * -> explicit column list)

Each rule returns a new SQL string (or None if it can't confidently repair).
"""

import re
from typing import Optional

import sqlglot
from sqlglot import exp

from src.error_diagnosis import Diagnosis


class RepairError(Exception):
    """Raised when no repair rule can confidently fix the query."""


# ---------- Rule 1: table name substitution ----------
def repair_missing_table(sql: str, diag: Diagnosis) -> Optional[str]:
    if not diag.bad_identifier or not diag.suggested_identifier:
        return None
    tree = sqlglot.parse_one(sql, read="postgres")
    for t in tree.find_all(exp.Table):
        if t.name == diag.bad_identifier:
            t.set("this", exp.to_identifier(diag.suggested_identifier))
    return tree.sql(dialect="postgres")


# ---------- Rule 2: column name substitution ----------
def repair_missing_column(sql: str, diag: Diagnosis) -> Optional[str]:
    if not diag.bad_identifier or not diag.suggested_identifier:
        return None
    tree = sqlglot.parse_one(sql, read="postgres")
    for c in tree.find_all(exp.Column):
        if c.name == diag.bad_identifier:
            c.set("this", exp.to_identifier(diag.suggested_identifier))
    return tree.sql(dialect="postgres")


# ---------- Rule 3: FK-based JOIN inference ----------
def repair_join_error(sql: str, diag: Diagnosis, schema: dict) -> Optional[str]:
    """
    If the query references two tables with no explicit join condition
    (or an invalid one) but a foreign key links them, inject
    'ON <fk.table>.<fk.column> = <ref_table>.<ref_column>'.
    """
    tree = sqlglot.parse_one(sql, read="postgres")
    tables = [t.name for t in tree.find_all(exp.Table)]
    if len(tables) < 2:
        return None

    fk_link = None
    for fk in schema.get("foreign_keys", []):
        if fk["table"] in tables and fk["ref_table"] in tables:
            fk_link = fk
            break
    if fk_link is None:
        return None

    join_condition = (
        f'{fk_link["table"]}.{fk_link["column"]} = '
        f'{fk_link["ref_table"]}.{fk_link["ref_column"]}'
    )

    joins = list(tree.find_all(exp.Join))
    if joins:
        # Attach ON clause to the first join lacking one
        for j in joins:
            if j.args.get("on") is None:
                j.set("on", sqlglot.condition(join_condition))
                return tree.sql(dialect="postgres")
        return None
    else:
        # No JOIN node parsed (likely comma-style join) -> rebuild as explicit JOIN
        select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
        from_clause = select.args.get("from")
        if from_clause is None:
            return None
        new_sql = re.sub(
            r"\bFROM\s+(\w+)\s*,\s*(\w+)\b",
            f'FROM \\1 JOIN \\2 ON {join_condition}',
            sql,
            flags=re.IGNORECASE,
        )
        return new_sql if new_sql != sql else None


# ---------- Rule 4: type cast insertion ----------
def repair_type_mismatch(sql: str, diag: Diagnosis, schema: dict) -> Optional[str]:
    """
    Look for equality/comparison predicates joining a text column with a
    numeric literal (or vice versa) and insert an explicit CAST.
    Simple, conservative heuristic rather than full type inference.
    """
    tree = sqlglot.parse_one(sql, read="postgres")
    column_types = {}
    for tname, tinfo in schema.get("tables", {}).items():
        for cname, ctype in tinfo.get("columns", {}).items():
            column_types[cname] = ctype

    changed = False
    for eq in tree.find_all(exp.EQ):
        left, right = eq.this, eq.expression
        col, lit = None, None
        if isinstance(left, exp.Column) and isinstance(right, exp.Literal):
            col, lit = left, right
        elif isinstance(right, exp.Column) and isinstance(left, exp.Literal):
            col, lit = right, left

        if col is None:
            continue

        col_type = column_types.get(col.name, "").lower()
        is_numeric_type = any(k in col_type for k in ("int", "numeric", "real", "double"))
        is_text_literal = lit.is_string

        if is_numeric_type and is_text_literal and lit.this.strip('"').isdigit():
            # 'id' = '5'  ->  id = 5   (or CAST if we want to be extra safe)
            new_lit = exp.Literal.number(lit.this.strip('"'))
            eq.set("expression" if eq.expression is lit else "this", new_lit)
            changed = True
        elif not is_numeric_type and not is_text_literal:
            # text column compared to a bare number -> cast literal to text
            eq.set(
                "expression" if eq.expression is lit else "this",
                exp.Cast(this=lit.copy(), to=exp.DataType.build("text")),
            )
            changed = True

    return tree.sql(dialect="postgres") if changed else None


# ---------- Rule 5: alias conflict resolution ----------
def repair_alias_conflict(sql: str, diag: Diagnosis) -> Optional[str]:
    """
    Detect duplicate table aliases in the FROM/JOIN clauses and
    rename the second occurrence to a unique alias (t2, t3, ...).
    """
    tree = sqlglot.parse_one(sql, read="postgres")
    seen = {}
    changed = False
    counter = 2
    for t in tree.find_all(exp.Table):
        alias = t.alias
        if not alias:
            continue
        if alias in seen and seen[alias] != t.name:
            new_alias = f"{alias}{counter}"
            counter += 1
            t.set("alias", exp.TableAlias(this=exp.to_identifier(new_alias)))
            changed = True
        else:
            seen[alias] = t.name
    return tree.sql(dialect="postgres") if changed else None


# ---------- Rule 6: SELECT * expansion ----------
def repair_select_star(sql: str, schema: dict) -> Optional[str]:
    """
    Replace SELECT * with an explicit column list drawn from the
    schema of the table(s) in the FROM clause.
    """
    tree = sqlglot.parse_one(sql, read="postgres")
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if select is None:
        return None

    has_star = any(isinstance(e, exp.Star) for e in select.expressions)
    if not has_star:
        return None

    tables = [t.name for t in select.find_all(exp.Table)]
    columns = []
    for t in tables:
        for c in schema.get("tables", {}).get(t, {}).get("columns", {}):
            columns.append(c)
    if not columns:
        return None

    select.set("expressions", [exp.column(c) for c in columns])
    return tree.sql(dialect="postgres")


# ---------- Dispatcher ----------
def repair(sql: str, diag: Diagnosis, schema: dict) -> str:
    """
    Route to the correct repair rule based on diagnosis category.
    Raises RepairError if no rule can produce a fix.
    """
    result = None

    if diag.category == "missing_table":
        result = repair_missing_table(sql, diag)
    elif diag.category == "missing_column":
        result = repair_missing_column(sql, diag)
    elif diag.category == "join_error":
        result = repair_join_error(sql, diag, schema)
    elif diag.category == "type_mismatch":
        result = repair_type_mismatch(sql, diag, schema)

    if result is None:
        # Fallback attempts: alias conflicts / SELECT * expansion can
        # co-occur with other error types and are cheap to try.
        result = repair_alias_conflict(sql, diag) or repair_select_star(sql, schema)

    if result is None:
        raise RepairError(f"No repair rule could fix category '{diag.category}': {diag.details}")

    return result
