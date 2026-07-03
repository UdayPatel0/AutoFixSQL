"""
config.py — Central configuration for AutoFixSQL.

Reads Postgres connection details from environment variables, falling back
to sensible local defaults. Edit the defaults or set env vars to point at
your Spider-loaded Postgres instance.

    export PGHOST=localhost
    export PGPORT=5432
    export PGDATABASE=spider_demo
    export PGUSER=postgres
    export PGPASSWORD=postgres
"""

import os
from dataclasses import dataclass


@dataclass
class DBConfig:
    host: str = os.environ.get("PGHOST", "localhost")
    port: int = int(os.environ.get("PGPORT", 5432))
    database: str = os.environ.get("PGDATABASE", "spider_demo")
    user: str = os.environ.get("PGUSER", "postgres")
    password: str = os.environ.get("PGPASSWORD", "postgres")

    def as_dict(self):
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
        }


# Bounded-retry defaults (used by retry_controller.py)
MAX_RETRIES = 3

# Similarity threshold (0-1) for difflib-based name matching in error_diagnosis.py
NAME_SIMILARITY_THRESHOLD = 0.6
