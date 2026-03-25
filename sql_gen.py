"""
SQL generation from extracted JSON data.
Converts structured extraction results into INSERT statements.
"""

from __future__ import annotations

import json
import re
from datetime import date


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def json_to_sql(
    data: dict,
    table_name: str,
    dialect: str = "mssql",
    schema_name: str = "dbo",
) -> str:
    """
    Convert extracted JSON to SQL INSERT statement(s).

    Scalar fields → one INSERT into the main table.
    Array fields (e.g. line_items) → separate INSERTs into a child table
    named <table>_<field> with a foreign-key-style reference column.

    Args:
        data: extracted JSON dict
        table_name: target table name
        dialect: 'mssql', 'postgres', or 'mysql'
        schema_name: schema/owner (default 'dbo' for SQL Server)

    Returns:
        SQL string with INSERT statement(s)
    """
    statements: list[str] = []
    scalar_cols: list[str] = []
    scalar_vals: list[str] = []
    array_fields: dict[str, list] = {}

    for field, value in data.items():
        if value is None:
            scalar_cols.append(field)
            scalar_vals.append("NULL")
        elif isinstance(value, list):
            array_fields[field] = value
        elif isinstance(value, dict):
            # Flatten one level: field_subfield
            for k, v in value.items():
                scalar_cols.append(f"{field}_{k}")
                scalar_vals.append(_format_value(v, dialect))
        else:
            scalar_cols.append(field)
            scalar_vals.append(_format_value(value, dialect))

    # Main table INSERT
    qualified = _qualify(table_name, schema_name, dialect)
    col_list = ", ".join(_quote_col(c, dialect) for c in scalar_cols)
    val_list = ", ".join(scalar_vals)
    statements.append(f"INSERT INTO {qualified} ({col_list})\nVALUES ({val_list});")

    # Child table INSERTs for array fields
    for field, items in array_fields.items():
        if not items:
            continue
        child_table = _qualify(f"{table_name}_{field}", schema_name, dialect)
        for i, item in enumerate(items):
            if isinstance(item, dict):
                child_cols = [_quote_col(k, dialect) for k in item.keys()]
                child_vals = [_format_value(v, dialect) for v in item.values()]
            else:
                child_cols = [_quote_col("value", dialect)]
                child_vals = [_format_value(item, dialect)]
            c_list = ", ".join(child_cols)
            v_list = ", ".join(child_vals)
            statements.append(f"INSERT INTO {child_table} ({c_list})\nVALUES ({v_list});")

    return "\n\n".join(statements)


def generate_create_table(
    data: dict,
    table_name: str,
    dialect: str = "mssql",
    schema_name: str = "dbo",
) -> str:
    """
    Generate CREATE TABLE DDL from extracted JSON structure.
    Useful for bootstrapping the target database.
    """
    statements: list[str] = []
    cols: list[str] = []
    array_fields: dict[str, list] = {}

    for field, value in data.items():
        if isinstance(value, list):
            array_fields[field] = value
        elif isinstance(value, dict):
            for k, v in value.items():
                cols.append(f"  {_quote_col(f'{field}_{k}', dialect)} {_infer_type(v, dialect)}")
        else:
            cols.append(f"  {_quote_col(field, dialect)} {_infer_type(value, dialect)}")

    qualified = _qualify(table_name, schema_name, dialect)
    col_block = ",\n".join(cols)
    statements.append(f"CREATE TABLE {qualified} (\n{col_block}\n);")

    # Child tables for arrays
    for field, items in array_fields.items():
        if not items or not isinstance(items[0], dict):
            continue
        child_qualified = _qualify(f"{table_name}_{field}", schema_name, dialect)
        child_cols = [
            f"  {_quote_col(k, dialect)} {_infer_type(v, dialect)}"
            for k, v in items[0].items()
        ]
        child_block = ",\n".join(child_cols)
        statements.append(f"CREATE TABLE {child_qualified} (\n{child_block}\n);")

    return "\n\n".join(statements)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_value(value, dialect: str) -> str:
    """Format a Python value as a SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace("'", "''")
    if dialect == "mssql":
        return f"N'{s}'"
    return f"'{s}'"


def _quote_col(name: str, dialect: str) -> str:
    """Quote a column name for the target dialect."""
    clean = re.sub(r"[^\w]", "_", name)
    if dialect == "mssql":
        return f"[{clean}]"
    if dialect == "postgres":
        return f'"{clean}"'
    return f"`{clean}`"


def _qualify(table: str, schema: str, dialect: str) -> str:
    """Fully qualify a table name."""
    clean = re.sub(r"[^\w]", "_", table)
    if dialect == "mssql":
        return f"[{schema}].[{clean}]"
    if dialect == "postgres" and schema:
        return f'"{schema}"."{clean}"'
    return f"`{clean}`"


def _infer_type(value, dialect: str) -> str:
    """Infer a SQL column type from a Python value."""
    if value is None:
        return "NVARCHAR(255)" if dialect == "mssql" else "TEXT"
    if isinstance(value, bool):
        return "BIT" if dialect == "mssql" else "BOOLEAN"
    if isinstance(value, int):
        return "INT"
    if isinstance(value, float):
        return "DECIMAL(18,2)"
    s = str(value)
    # Check if it looks like a date
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return "DATE"
    if dialect == "mssql":
        return "NVARCHAR(500)"
    return "TEXT"
