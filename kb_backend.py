"""
Knowledge Base storage backends — SQLite and SQL Server.

Abstracts dialect differences so knowledge_base.py doesn't care which DB
is in use.  Both backends implement the same KBBackend protocol.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Protocol (structural typing — no inheritance required)
# ---------------------------------------------------------------------------

class KBBackend(Protocol):
    def ensure_table(self, table: str, sample_row: dict) -> None: ...
    def insert_row(self, table: str, data: dict) -> int: ...
    def list_tables(self) -> list[str]: ...
    def get_table_info(self, table: str) -> list[dict]: ...
    def get_row_count(self, table: str) -> int: ...
    def execute_query(self, sql: str) -> list[dict]: ...
    def get_sample_rows(self, table: str, limit: int = 2) -> list[dict]: ...
    def sql_dialect(self) -> str: ...
    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# SQLite backend (local dev / fallback)
# ---------------------------------------------------------------------------

class SQLiteBackend:
    """SQLite-based KB backend."""

    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

    @staticmethod
    def _infer_type(value: Any) -> str:
        if isinstance(value, bool):
            return "INTEGER"
        if isinstance(value, int):
            return "INTEGER"
        if isinstance(value, float):
            return "REAL"
        return "TEXT"

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return value

    def ensure_table(self, table: str, sample_row: dict) -> None:
        """Create table if missing; add any new columns."""
        exists = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()

        if not exists:
            col_defs = ", ".join(
                f'"{k}" {self._infer_type(v)}' for k, v in sample_row.items()
            )
            self._conn.execute(
                f'CREATE TABLE "{table}" '
                f"(id INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})"
            )
            return

        existing_cols = {
            row["name"]
            for row in self._conn.execute(
                f'PRAGMA table_info("{table}")'
            ).fetchall()
        }
        for col, value in sample_row.items():
            if col not in existing_cols:
                self._conn.execute(
                    f'ALTER TABLE "{table}" ADD COLUMN '
                    f'"{col}" {self._infer_type(value)}'
                )

    def insert_row(self, table: str, data: dict) -> int:
        """Insert a row and return the new row id."""
        cols = list(data.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_list = ", ".join(f'"{c}"' for c in cols)
        self._conn.execute(
            f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})',
            [self._serialize(data[c]) for c in cols],
        )
        row_id = self._conn.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]
        self._conn.commit()
        return row_id

    def list_tables(self) -> list[str]:
        """Return all user table names."""
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [row["name"] for row in rows]

    def get_table_info(self, table: str) -> list[dict]:
        """Return column metadata for a table."""
        rows = self._conn.execute(
            f'PRAGMA table_info("{table}")'
        ).fetchall()
        return [
            {"name": row["name"], "type": row["type"]}
            for row in rows
        ]

    def get_row_count(self, table: str) -> int:
        """Return the number of rows in a table."""
        row = self._conn.execute(
            f'SELECT COUNT(*) as c FROM "{table}"'
        ).fetchone()
        return row["c"]

    def execute_query(self, sql: str) -> list[dict]:
        """Execute arbitrary SQL and return results as dicts."""
        rows = self._conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def get_sample_rows(self, table: str, limit: int = 2) -> list[dict]:
        """Return a few sample rows for schema context."""
        rows = self._conn.execute(
            f'SELECT * FROM "{table}" LIMIT ?', (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def sql_dialect(self) -> str:
        return "sqlite"

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()


# ---------------------------------------------------------------------------
# MSSQL backend (production / per-org Azure SQL Database)
# ---------------------------------------------------------------------------

class MSSQLBackend:
    """SQL Server backend for per-org Azure SQL Databases."""

    def __init__(
        self,
        server: str,
        database: str,
        user: str,
        password: str,
        port: int = 1433,
    ):
        import pymssql
        self._conn = pymssql.connect(
            server=server, user=user, password=password,
            port=port, database=database,
        )

    @staticmethod
    def _infer_type(value: Any) -> str:
        if isinstance(value, bool):
            return "BIT"
        if isinstance(value, int):
            return "INT"
        if isinstance(value, float):
            return "DECIMAL(18,2)"
        return "NVARCHAR(500)"

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return value

    def ensure_table(self, table: str, sample_row: dict) -> None:
        """Create table if missing; add any new columns (T-SQL)."""
        cursor = self._conn.cursor(as_dict=True)

        # Check if table exists
        cursor.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = %s",
            (table,),
        )
        exists = cursor.fetchone()

        if not exists:
            col_defs = ", ".join(
                f"[{k}] {self._infer_type(v)}" for k, v in sample_row.items()
            )
            cursor.execute(
                f"CREATE TABLE [dbo].[{table}] "
                f"([id] INT IDENTITY(1,1) PRIMARY KEY, {col_defs})"
            )
            self._conn.commit()
            return

        # Add missing columns
        cursor.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = %s",
            (table,),
        )
        existing_cols = {row["COLUMN_NAME"] for row in cursor.fetchall()}

        for col, value in sample_row.items():
            if col not in existing_cols:
                cursor.execute(
                    f"ALTER TABLE [dbo].[{table}] "
                    f"ADD [{col}] {self._infer_type(value)}"
                )
        self._conn.commit()

    def insert_row(self, table: str, data: dict) -> int:
        """Insert a row and return the SCOPE_IDENTITY()."""
        cursor = self._conn.cursor()
        cols = list(data.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        col_list = ", ".join(f"[{c}]" for c in cols)

        cursor.execute(
            f"INSERT INTO [dbo].[{table}] ({col_list}) VALUES ({placeholders})",
            tuple(self._serialize(data[c]) for c in cols),
        )
        cursor.execute("SELECT SCOPE_IDENTITY()")
        row_id = cursor.fetchone()[0]
        self._conn.commit()
        return int(row_id) if row_id is not None else 0

    def list_tables(self) -> list[str]:
        """Return all user table names in the dbo schema."""
        cursor = self._conn.cursor(as_dict=True)
        cursor.execute(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = 'dbo' AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
        return [row["TABLE_NAME"] for row in cursor.fetchall()]

    def get_table_info(self, table: str) -> list[dict]:
        """Return column metadata for a table."""
        cursor = self._conn.cursor(as_dict=True)
        cursor.execute(
            "SELECT COLUMN_NAME, DATA_TYPE "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION",
            (table,),
        )
        return [
            {"name": row["COLUMN_NAME"], "type": row["DATA_TYPE"]}
            for row in cursor.fetchall()
        ]

    def get_row_count(self, table: str) -> int:
        """Return the number of rows in a table."""
        cursor = self._conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM [dbo].[{table}]")
        return cursor.fetchone()[0]

    def execute_query(self, sql: str) -> list[dict]:
        """Execute arbitrary SQL and return results as dicts."""
        cursor = self._conn.cursor(as_dict=True)
        cursor.execute(sql)
        return [dict(r) for r in cursor.fetchall()]

    def get_sample_rows(self, table: str, limit: int = 2) -> list[dict]:
        """Return a few sample rows for schema context."""
        cursor = self._conn.cursor(as_dict=True)
        cursor.execute(
            f"SELECT TOP {int(limit)} * FROM [dbo].[{table}]"
        )
        return [dict(r) for r in cursor.fetchall()]

    def sql_dialect(self) -> str:
        return "tsql"

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _persistent_root() -> Path:
    """Use persistent storage on Azure, local otherwise."""
    azure_data = Path("/home/data")
    if azure_data.exists():
        return azure_data / "knowledge_bases"
    return Path(__file__).parent / "knowledge_bases"


KB_DIR = _persistent_root()


def get_backend(customer_id: str) -> KBBackend:
    """
    Return the appropriate backend for a customer.

    - If Azure SQL is configured AND the org has a provisioned DB -> MSSQLBackend
    - Otherwise -> SQLiteBackend (local file)
    """
    from db_provisioner import is_azure_sql_configured
    import metadata as md

    if is_azure_sql_configured():
        # Extract org_id from customer_id (format: "org_id" or "org_id__project_id")
        org_id = customer_id.split("__")[0]
        org_db = md.get_org_database(org_id)
        if org_db and org_db.status == "ready":
            return MSSQLBackend(
                server=org_db.server,
                database=org_db.database_name,
                user=org_db.username,
                password=org_db.password_encrypted,
                port=org_db.port,
            )

    # Fallback to SQLite
    KB_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^\w\-]", "_", customer_id)
    db_path = KB_DIR / f"{safe_id}.db"
    return SQLiteBackend(db_path)
