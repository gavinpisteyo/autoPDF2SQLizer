"""
Knowledge Base — per-customer structured data store with Text-to-SQL RAG.

Each customer's extracted data is stored in isolated databases (SQLite for
local dev, Azure SQL per-org in production).  Queries are answered by:
  1. LLM generates SQL from natural language (dialect-aware)
  2. SQL executes against the customer's data
  3. LLM explains the results in natural language

No vector DB or embeddings needed — the data is already structured.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from anthropic import Anthropic

from kb_backend import KBBackend, get_backend

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def resolve_kb_id(org_id: str, project_id: str = "") -> str:
    """Build a knowledge base ID from org + optional project context."""
    if project_id:
        return f"{org_id}__{project_id}"
    return org_id


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
    backend = get_backend(customer_id)
    try:
        table = re.sub(r"[^\w]", "_", doc_type)
        scalars, arrays = _split_fields(extracted_data)
        scalars["_source_file"] = source_file
        scalars["_doc_type"] = doc_type

        backend.ensure_table(table, scalars)
        row_id = backend.insert_row(table, scalars)

        child_counts = _insert_child_rows(backend, table, row_id, arrays)
    finally:
        backend.close()

    return IndexResult(table_name=table, rows_inserted=1, child_tables=child_counts)


def _split_fields(data: dict) -> tuple[dict, dict]:
    """Separate scalar and array fields; flatten nested dicts."""
    scalars: dict = {}
    arrays: dict = {}
    for key, value in data.items():
        if isinstance(value, list):
            arrays[key] = value
        elif isinstance(value, dict):
            for k, v in value.items():
                scalars[f"{key}_{k}"] = v
        else:
            scalars[key] = value
    return scalars, arrays


def _insert_child_rows(
    backend: KBBackend,
    parent_table: str,
    parent_id: int,
    arrays: dict,
) -> dict[str, int]:
    """Insert child rows for array fields into child tables."""
    child_counts: dict[str, int] = {}
    for field, items in arrays.items():
        if not items:
            continue
        child_table = f"{parent_table}_{field}"
        for item in items:
            if isinstance(item, dict):
                child_row = {f"{parent_table}_id": parent_id, **item}
            else:
                child_row = {f"{parent_table}_id": parent_id, "value": item}
            backend.ensure_table(child_table, child_row)
            backend.insert_row(child_table, child_row)
        child_counts[child_table] = len(items)
    return child_counts


# ---------------------------------------------------------------------------
# Schema introspection (for the LLM)
# ---------------------------------------------------------------------------

def get_schema_description(customer_id: str) -> str:
    """
    Get a human/LLM-readable description of all tables and columns
    in a customer's knowledge base.
    """
    backend = get_backend(customer_id)
    try:
        tables = backend.list_tables()
        if not tables:
            return "No data stored yet."

        lines = _build_table_descriptions(backend, tables)
        lines.extend(_build_sample_descriptions(backend, tables))
    finally:
        backend.close()

    return "\n".join(lines)


def _build_table_descriptions(
    backend: KBBackend, tables: list[str],
) -> list[str]:
    """Build table + column summary lines."""
    lines = []
    for name in tables:
        cols = backend.get_table_info(name)
        count = backend.get_row_count(name)
        col_list = ", ".join(
            f'{c["name"]} ({c["type"]})' for c in cols
        )
        lines.append(f'Table "{name}" ({count} rows): {col_list}')
    return lines


def _build_sample_descriptions(
    backend: KBBackend, tables: list[str],
) -> list[str]:
    """Build sample-data lines for LLM context."""
    lines = []
    for name in tables:
        sample = backend.get_sample_rows(name, limit=2)
        if sample:
            lines.append(f'\nSample from "{name}":')
            for row in sample:
                lines.append(f"  {row}")
    return lines


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats(customer_id: str) -> dict:
    """Get summary stats for a customer's knowledge base."""
    backend = get_backend(customer_id)
    try:
        tables = backend.list_tables()
        if not tables:
            return {"exists": False, "tables": [], "total_rows": 0}

        table_stats = []
        total_rows = 0
        for name in tables:
            count = backend.get_row_count(name)
            total_rows += count
            table_stats.append({"name": name, "rows": count})
    finally:
        backend.close()

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


_SQLITE_SQL_RULES = """Rules:
- Return ONLY the SQL query, nothing else
- Use SQLite syntax
- Use double quotes for identifiers
- Handle NULLs appropriately
- For text searches, use LIKE with % wildcards (case-insensitive)
- Limit results to 50 rows max
- If the question can't be answered from the data, return: SELECT 'No relevant data found' as answer"""

_TSQL_SQL_RULES = """Rules:
- Return ONLY the SQL query, nothing else
- Use T-SQL syntax
- Use [brackets] for identifiers
- Use N'' for string literals
- Use TOP instead of LIMIT
- Prefix tables with [dbo] schema (e.g. [dbo].[table_name])
- Handle NULLs appropriately
- For text searches, use LIKE with % wildcards (case-insensitive)
- Limit results to 50 rows max (use SELECT TOP 50)
- If the question can't be answered from the data, return: SELECT 'No relevant data found' as answer"""


def query(customer_id: str, question: str) -> QueryResult:
    """
    Answer a natural language question about a customer's data.

    1. Get the schema description
    2. Ask Claude to generate SQL (dialect-aware)
    3. Execute the SQL
    4. Ask Claude to explain the results
    """
    schema_desc = get_schema_description(customer_id)
    if schema_desc == "No data stored yet.":
        return QueryResult(
            question=question,
            sql_generated="",
            raw_results=[],
            answer="No data has been indexed yet. Upload and extract some documents first.",
        )

    backend = get_backend(customer_id)
    try:
        dialect = backend.sql_dialect()
        sql_text = _generate_sql(schema_desc, question, dialect)
        raw_results, error = _execute_sql(backend, sql_text)
    finally:
        backend.close()

    if error:
        return QueryResult(
            question=question,
            sql_generated=sql_text,
            raw_results=[],
            answer=f"Query failed: {error}",
            error=error,
        )

    answer = _generate_answer(question, raw_results)

    return QueryResult(
        question=question,
        sql_generated=sql_text,
        raw_results=raw_results,
        answer=answer,
    )


def _generate_sql(schema_desc: str, question: str, dialect: str) -> str:
    """Use Claude to generate SQL from the question and schema."""
    client = Anthropic()
    rules = _TSQL_SQL_RULES if dialect == "tsql" else _SQLITE_SQL_RULES
    dialect_label = "T-SQL" if dialect == "tsql" else "SQLite"

    sql_prompt = (
        f"You are a SQL query generator. Given the database schema below,\n"
        f"generate a {dialect_label} query to answer the user's question.\n\n"
        f"DATABASE SCHEMA:\n{schema_desc}\n\n{rules}"
    )

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
    return sql_text


def _execute_sql(
    backend: KBBackend, sql_text: str,
) -> tuple[list[dict], str | None]:
    """Execute SQL on the backend, returning (results, error)."""
    try:
        raw_results = backend.execute_query(sql_text)
        return raw_results, None
    except Exception as e:
        return [], str(e)


def _generate_answer(question: str, raw_results: list[dict]) -> str:
    """Use Claude to produce a natural language answer from query results."""
    client = Anthropic()

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
                "content": (
                    f"Question: {question}\n\n"
                    f"Query results ({len(raw_results)} rows):\n{result_text}"
                ),
            }
        ],
    )
    return answer_response.content[0].text


# ---------------------------------------------------------------------------
# List customers
# ---------------------------------------------------------------------------

def list_customers() -> list[dict]:
    """
    List all customers with knowledge bases.
    Checks both SQLite files and org_databases in metadata.
    """
    from kb_backend import KB_DIR
    import metadata as md

    customers: dict[str, dict] = {}

    # SQLite file-based knowledge bases
    KB_DIR.mkdir(parents=True, exist_ok=True)
    for db_file in sorted(KB_DIR.glob("*.db")):
        customer_id = db_file.stem
        stats = get_stats(customer_id)
        customers[customer_id] = {"customer_id": customer_id, **stats}

    # Azure SQL-backed knowledge bases from metadata
    from db_provisioner import is_azure_sql_configured
    if is_azure_sql_configured():
        conn = md._get_conn()
        rows = conn.execute(
            "SELECT org_id, status FROM org_databases WHERE status = 'ready'"
        ).fetchall()
        conn.close()
        for row in rows:
            org_id = row["org_id"]
            if org_id not in customers:
                stats = get_stats(org_id)
                customers[org_id] = {"customer_id": org_id, **stats}

    return list(customers.values())
