"""
Knowledge Base — per-customer structured data store with Text-to-SQL RAG.

Each customer's extracted data is stored in isolated SQLite databases.
Queries are answered by:
  1. LLM generates SQL from natural language
  2. SQL executes against the customer's data
  3. LLM explains the results in natural language

No vector DB or embeddings needed — the data is already structured.
"""

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

KB_DIR = Path(__file__).parent / "knowledge_bases"


def _db_path(customer_id: str) -> Path:
    """Path to a customer's SQLite database."""
    KB_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^\w\-]", "_", customer_id)
    return KB_DIR / f"{safe_id}.db"


def _get_conn(customer_id: str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(customer_id)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _infer_sqlite_type(value) -> str:
    if value is None:
        return "TEXT"
    if isinstance(value, bool):
        return "INTEGER"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    return "TEXT"


# ---------------------------------------------------------------------------
# Index (store extracted data)
# ---------------------------------------------------------------------------

@dataclass
class IndexResult:
    table_name: str
    rows_inserted: int
    child_tables: dict[str, int]


def index_document(
    customer_id: str,
    doc_type: str,
    extracted_data: dict,
    source_file: str = "",
) -> IndexResult:
    """
    Store extracted data in the customer's knowledge base.

    Creates the table if it doesn't exist (schema inferred from data).
    Scalar fields go into the main table. Array fields go into child tables.
    """
    conn = _get_conn(customer_id)
    table = re.sub(r"[^\w]", "_", doc_type)

    # Separate scalar and array fields
    scalars = {}
    arrays = {}
    for key, value in extracted_data.items():
        if isinstance(value, list):
            arrays[key] = value
        elif isinstance(value, dict):
            for k, v in value.items():
                scalars[f"{key}_{k}"] = v
        else:
            scalars[key] = value

    # Add metadata
    scalars["_source_file"] = source_file
    scalars["_doc_type"] = doc_type

    # Ensure main table exists
    _ensure_table(conn, table, scalars)

    # Insert main row
    cols = list(scalars.keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join(f'"{c}"' for c in cols)
    conn.execute(
        f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})',
        [_serialize(scalars[c]) for c in cols],
    )
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Insert child rows for array fields
    child_counts = {}
    for field, items in arrays.items():
        if not items:
            continue
        child_table = f"{table}_{field}"
        for item in items:
            if isinstance(item, dict):
                child_row = {f"{table}_id": row_id, **item}
            else:
                child_row = {f"{table}_id": row_id, "value": item}
            _ensure_table(conn, child_table, child_row)
            child_cols = list(child_row.keys())
            child_placeholders = ", ".join(["?"] * len(child_cols))
            child_col_list = ", ".join(f'"{c}"' for c in child_cols)
            conn.execute(
                f'INSERT INTO "{child_table}" ({child_col_list}) VALUES ({child_placeholders})',
                [_serialize(child_row[c]) for c in child_cols],
            )
        child_counts[child_table] = len(items)

    conn.commit()
    conn.close()

    return IndexResult(table_name=table, rows_inserted=1, child_tables=child_counts)


def _ensure_table(conn: sqlite3.Connection, table: str, sample_row: dict):
    """Create table if it doesn't exist, add missing columns."""
    # Check if table exists
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()

    if not exists:
        col_defs = ", ".join(
            f'"{k}" {_infer_sqlite_type(v)}' for k, v in sample_row.items()
        )
        conn.execute(
            f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})'
        )
        return

    # Add any missing columns
    existing_cols = {
        row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }
    for col, value in sample_row.items():
        if col not in existing_cols:
            conn.execute(
                f'ALTER TABLE "{table}" ADD COLUMN "{col}" {_infer_sqlite_type(value)}'
            )


def _serialize(value):
    """Serialize a value for SQLite storage."""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


# ---------------------------------------------------------------------------
# Schema introspection (for the LLM)
# ---------------------------------------------------------------------------

def get_schema_description(customer_id: str) -> str:
    """
    Get a human/LLM-readable description of all tables and columns
    in a customer's knowledge base.
    """
    path = _db_path(customer_id)
    if not path.exists():
        return "No data stored yet."

    conn = _get_conn(customer_id)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    if not tables:
        conn.close()
        return "No tables found."

    lines = []
    for t in tables:
        name = t["name"]
        cols = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        count = conn.execute(f'SELECT COUNT(*) as c FROM "{name}"').fetchone()["c"]
        col_list = ", ".join(f'{c["name"]} ({c["type"]})' for c in cols)
        lines.append(f'Table "{name}" ({count} rows): {col_list}')

    # Include some sample data for context
    for t in tables:
        name = t["name"]
        sample = conn.execute(f'SELECT * FROM "{name}" LIMIT 2').fetchall()
        if sample:
            lines.append(f'\nSample from "{name}":')
            for row in sample:
                lines.append(f"  {dict(row)}")

    conn.close()
    return "\n".join(lines)


def get_stats(customer_id: str) -> dict:
    """Get summary stats for a customer's knowledge base."""
    path = _db_path(customer_id)
    if not path.exists():
        return {"exists": False, "tables": [], "total_rows": 0}

    conn = _get_conn(customer_id)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    table_stats = []
    total_rows = 0
    for t in tables:
        name = t["name"]
        count = conn.execute(f'SELECT COUNT(*) as c FROM "{name}"').fetchone()["c"]
        total_rows += count
        table_stats.append({"name": name, "rows": count})

    conn.close()
    return {"exists": True, "tables": table_stats, "total_rows": total_rows}


# ---------------------------------------------------------------------------
# RAG Query — Text-to-SQL + natural language answer
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    question: str
    sql_generated: str
    raw_results: list[dict]
    answer: str
    error: str | None = None


def query(customer_id: str, question: str) -> QueryResult:
    """
    Answer a natural language question about a customer's data.

    1. Get the schema description
    2. Ask Claude to generate SQL
    3. Execute the SQL
    4. Ask Claude to explain the results
    """
    client = Anthropic()

    schema_desc = get_schema_description(customer_id)
    if schema_desc == "No data stored yet.":
        return QueryResult(
            question=question,
            sql_generated="",
            raw_results=[],
            answer="No data has been indexed yet. Upload and extract some documents first.",
        )

    # Step 1: Generate SQL
    sql_prompt = f"""You are a SQL query generator. Given the database schema below,
generate a SQLite query to answer the user's question.

DATABASE SCHEMA:
{schema_desc}

Rules:
- Return ONLY the SQL query, nothing else
- Use SQLite syntax
- Use double quotes for identifiers
- Handle NULLs appropriately
- For text searches, use LIKE with % wildcards (case-insensitive)
- Limit results to 50 rows max
- If the question can't be answered from the data, return: SELECT 'No relevant data found' as answer"""

    sql_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        temperature=0.0,
        system=sql_prompt,
        messages=[{"role": "user", "content": question}],
    )
    sql_text = sql_response.content[0].text.strip()

    # Clean SQL (remove markdown fences if present)
    sql_text = re.sub(r"^```\w*\n?", "", sql_text)
    sql_text = re.sub(r"\n?```$", "", sql_text).strip()

    # Step 2: Execute SQL
    conn = _get_conn(customer_id)
    raw_results = []
    error = None
    try:
        rows = conn.execute(sql_text).fetchall()
        raw_results = [dict(r) for r in rows]
    except Exception as e:
        error = str(e)
    finally:
        conn.close()

    if error:
        return QueryResult(
            question=question,
            sql_generated=sql_text,
            raw_results=[],
            answer=f"Query failed: {error}",
            error=error,
        )

    # Step 3: Generate natural language answer
    answer_prompt = """You are a helpful data analyst. Given the user's question
and the query results, provide a clear, concise natural language answer.

Rules:
- Be specific with numbers, dates, and names
- If results are empty, say so clearly
- Format currency values with $ and commas
- Keep it conversational but precise"""

    result_text = json.dumps(raw_results[:20], indent=2, default=str)
    answer_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        temperature=0.0,
        system=answer_prompt,
        messages=[
            {
                "role": "user",
                "content": f"Question: {question}\n\nQuery results ({len(raw_results)} rows):\n{result_text}",
            }
        ],
    )

    return QueryResult(
        question=question,
        sql_generated=sql_text,
        raw_results=raw_results,
        answer=answer_response.content[0].text,
    )


# ---------------------------------------------------------------------------
# List customers
# ---------------------------------------------------------------------------

def list_customers() -> list[dict]:
    """List all customers with knowledge bases."""
    KB_DIR.mkdir(parents=True, exist_ok=True)
    customers = []
    for db_file in sorted(KB_DIR.glob("*.db")):
        customer_id = db_file.stem
        stats = get_stats(customer_id)
        customers.append({"customer_id": customer_id, **stats})
    return customers
