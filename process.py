"""
PDF to structured data extraction logic.
============================================================
★  THIS IS THE FILE THE WIGGUM LOOP AGENT MODIFIES.  ★
============================================================

The pipeline:
1. Receives raw Azure Document Intelligence output (cached JSON)
2. Pre-processes it into a text representation
3. Sends it to Claude with the target schema
4. Post-processes the result

Everything is fair game: prompts, parsing logic, field mapping,
normalization, validation, post-processing, LLM parameters.
"""

import json
import os
import re
from pathlib import Path

from anthropic import Anthropic

# ---------------------------------------------------------------------------
# Configuration (agent can tune these)
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096
TEMPERATURE = 0.0

# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

client = Anthropic()

PROMPTS_DIR = Path(__file__).parent / "prompts"


# ---------------------------------------------------------------------------
# Main entry point — called by evaluate.py and app.py
# ---------------------------------------------------------------------------

def extract(raw_doc_intel: dict, doc_type: str, schema: dict) -> dict:
    """
    Extract structured data from raw Document Intelligence output.

    Args:
        raw_doc_intel: Raw Azure Document Intelligence analyzeResult
        doc_type: Document type key (e.g. 'invoice', 'contract')
        schema: Target JSON Schema defining expected output fields

    Returns:
        dict whose keys match schema properties
    """
    # Step 1 — build a text representation of the document
    content = pre_process(raw_doc_intel, doc_type)

    # Step 2 — ask the LLM to extract structured data
    extracted = llm_extract(content, doc_type, schema)

    # Step 3 — deterministic post-processing / normalization
    result = post_process(extracted, doc_type, schema)

    return result


# ---------------------------------------------------------------------------
# Pre-processing  (prepare Doc Intel JSON for the LLM)
# ---------------------------------------------------------------------------

def pre_process(raw: dict, doc_type: str) -> str:
    """Convert raw Doc Intel output into a text representation."""
    sections: list[str] = []

    # Key-value pairs (if the model returned any)
    kvs = raw.get("keyValuePairs") or []
    if kvs:
        sections.append("KEY-VALUE PAIRS:")
        for kv in kvs:
            key = (kv.get("key") or {}).get("content", "")
            value = (kv.get("value") or {}).get("content", "")
            conf = kv.get("confidence", 0)
            sections.append(f"  {key}: {value}  (confidence {conf:.2f})")

    # Tables
    tables = raw.get("tables") or []
    for idx, table in enumerate(tables):
        sections.append(f"\nTABLE {idx + 1}:")
        rows: dict[int, dict[int, str]] = {}
        for cell in table.get("cells", []):
            r = cell.get("rowIndex", 0)
            c = cell.get("columnIndex", 0)
            rows.setdefault(r, {})[c] = cell.get("content", "")
        if rows:
            max_col = max(c for row in rows.values() for c in row) + 1
            for r in sorted(rows):
                vals = [rows[r].get(c, "") for c in range(max_col)]
                sections.append("  | " + " | ".join(vals) + " |")

    # Full text as fallback context
    full_text = raw.get("content", "")
    if full_text:
        sections.append(f"\nFULL TEXT:\n{full_text}")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# LLM Extraction
# ---------------------------------------------------------------------------

def load_prompt(doc_type: str) -> str:
    """Load the type-specific extraction prompt (if one exists)."""
    path = PROMPTS_DIR / f"{doc_type}.md"
    if path.exists():
        return path.read_text()
    return ""


def llm_extract(content: str, doc_type: str, schema: dict) -> dict:
    """Send document content + schema to Claude, get structured JSON back."""

    type_prompt = load_prompt(doc_type)

    system = f"""You are a document data extraction expert.
Extract structured data from the document content below.

Target JSON Schema:
{json.dumps(schema, indent=2)}

{type_prompt}

Rules:
- Return ONLY valid JSON matching the schema — no markdown fences, no explanation.
- Use null for fields you cannot confidently find.
- Dates must be YYYY-MM-DD.
- Currency amounts must be plain numbers (no $ € £ symbols, no commas).
- For arrays, include every item found in the document."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=system,
        messages=[{"role": "user", "content": content}],
    )

    text = response.content[0].text

    # Parse JSON — handle the LLM sometimes wrapping in markdown
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}


# ---------------------------------------------------------------------------
# Post-processing  (deterministic cleanup / normalization)
# ---------------------------------------------------------------------------

def post_process(data: dict, doc_type: str, schema: dict) -> dict:
    """Apply deterministic post-processing rules after LLM extraction."""
    result: dict = {}
    properties = schema.get("properties", {})

    for field, field_schema in properties.items():
        value = data.get(field)
        if value is None:
            result[field] = None
            continue
        result[field] = normalize_value(value, field_schema)

    return result


def normalize_value(value, field_schema: dict):
    """Normalize a single value to match its declared schema type."""
    if value is None:
        return None

    field_type = field_schema.get("type", "string")

    if field_type == "number":
        return _normalize_number(value)
    elif field_type == "string":
        return str(value).strip()
    elif field_type == "array":
        items_schema = field_schema.get("items", {})
        if not isinstance(value, list):
            value = [value]
        return [normalize_value(item, items_schema) for item in value]
    elif field_type == "object":
        if isinstance(value, dict):
            obj_props = field_schema.get("properties", {})
            return {
                k: normalize_value(v, obj_props.get(k, {}))
                for k, v in value.items()
            }
        return value
    return value


def _normalize_number(value) -> float | None:
    """Best-effort conversion to float."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = re.sub(r"[^\d.\-]", "", str(value))
        return float(cleaned)
    except (ValueError, TypeError):
        return None
