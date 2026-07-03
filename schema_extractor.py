"""
schema_extractor.py — Pulls schema metadata from PostgreSQL.

Extracts table names, column names, data types, and foreign-key
constraints using psycopg2 + information_schema, and returns a single
Python dict that the diagnosis and repair modules can consume.

Schema dict shape:
{
    "tables": {
        "students": {
            "columns": {
                "id": "integer",
                "name": "character varying",
                ...
            },
            "primary_key": ["id"],
        },
        ...
    },
    "foreign_keys": [
        {
            "table": "enrollments",
            "column": "student_id",
            "ref_table": "students",
            "ref_column": "id",
        },
        ...
    ],
}
"""

import psycopg2
from src.config import DBConfig


def get_connection(db_config: DBConfig = None):
    db_config = db_config or DBConfig()
    return psycopg2.connect(**db_config.as_dict())


def extract_schema(conn=None, db_config: DBConfig = None) -> dict:
    """
    Extract full schema metadata (tables, columns, types, PKs, FKs)
    from the connected Postgres database's public schema.
    """
    own_conn = conn is None
    conn = conn or get_connection(db_config)
    schema = {"tables": {}, "foreign_keys": []}

    try:
        with conn.cursor() as cur:
            # --- Tables + columns + types ---
            cur.execute("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
            """)
            for table_name, column_name, data_type in cur.fetchall():
                t = schema["tables"].setdefault(
                    table_name, {"columns": {}, "primary_key": []}
                )
                t["columns"][column_name] = data_type

            # --- Primary keys ---
            cur.execute("""
                SELECT tc.table_name, kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema = 'public';
            """)
            for table_name, column_name in cur.fetchall():
                if table_name in schema["tables"]:
                    schema["tables"][table_name]["primary_key"].append(column_name)

            # --- Foreign keys ---
            cur.execute("""
                SELECT
                    tc.table_name, kcu.column_name,
                    ccu.table_name AS ref_table, ccu.column_name AS ref_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON tc.constraint_name = ccu.constraint_name
                 AND tc.table_schema = ccu.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public';
            """)
            for table_name, column_name, ref_table, ref_column in cur.fetchall():
                schema["foreign_keys"].append({
                    "table": table_name,
                    "column": column_name,
                    "ref_table": ref_table,
                    "ref_column": ref_column,
                })
    finally:
        if own_conn:
            conn.close()

    return schema


if __name__ == "__main__":
    import json
    s = extract_schema()
    print(json.dumps(s, indent=2))
