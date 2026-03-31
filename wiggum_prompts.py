"""Prompts for the Wiggum loop -- initial code generation and iterative improvement."""
from __future__ import annotations

import json
import re


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def truncate_di_output(raw_di_json: dict, max_chars: int = 8000) -> str:
    """
    Truncate Document Intelligence output for Claude context.

    Prioritizes key-value pairs and tables, then falls back to raw content.
    """
    sections: list[str] = []
    chars_used = 0

    # Key-value pairs (most useful for extraction)
    kvs = raw_di_json.get("keyValuePairs") or []
    if kvs:
        kv_lines = ["KEY-VALUE PAIRS:"]
        for kv in kvs:
            key = (kv.get("key") or {}).get("content", "")
            value = (kv.get("value") or {}).get("content", "")
            conf = kv.get("confidence", 0)
            kv_lines.append(f"  {key}: {value}  (confidence {conf:.2f})")
        kv_block = "\n".join(kv_lines)
        if chars_used + len(kv_block) < max_chars:
            sections.append(kv_block)
            chars_used += len(kv_block)

    # Tables
    tables = raw_di_json.get("tables") or []
    for idx, table in enumerate(tables):
        table_lines = [f"\nTABLE {idx + 1}:"]
        rows: dict[int, dict[int, str]] = {}
        for cell in table.get("cells", []):
            r = cell.get("rowIndex", 0)
            c = cell.get("columnIndex", 0)
            rows.setdefault(r, {})[c] = cell.get("content", "")
        if rows:
            max_col = max(c for row_data in rows.values() for c in row_data) + 1
            for r in sorted(rows):
                vals = [rows[r].get(c, "") for c in range(max_col)]
                table_lines.append("  | " + " | ".join(vals) + " |")
        table_block = "\n".join(table_lines)
        if chars_used + len(table_block) < max_chars:
            sections.append(table_block)
            chars_used += len(table_block)

    # Full text (truncated to fill remaining budget)
    full_text = raw_di_json.get("content", "")
    if full_text:
        remaining = max_chars - chars_used - 20  # leave room for header
        if remaining > 200:
            truncated = full_text[:remaining]
            if len(full_text) > remaining:
                truncated += "\n... [TRUNCATED]"
            sections.append(f"\nFULL TEXT:\n{truncated}")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Initial code generation prompt
# ---------------------------------------------------------------------------

_INITIAL_SYSTEM = """\
You are an expert Python developer specializing in document data extraction.

Your task: write a Python function that extracts structured data from Azure \
Document Intelligence (DI) output.

## What you receive

The function signature is:
```python
def extract(raw_data: dict, schema: dict, prompt: str) -> dict:
```

- `raw_data` is the Azure Document Intelligence analyzeResult JSON. Key fields:
  - `raw_data["keyValuePairs"]`: list of {{key: {{content: str}}, value: {{content: str}}, confidence: float}}
  - `raw_data["tables"]`: list of tables, each with `cells` (rowIndex, columnIndex, content)
  - `raw_data["content"]`: full OCR text of the document
  - `raw_data["pages"]`: list of pages with lines and words

- `schema` is a JSON Schema dict. `schema["properties"]` defines each field to extract, \
  with "type" (string, number, array, object) and optional "description".

- `prompt` is a natural-language hint (may be empty).

## What you must return

A dict whose keys match `schema["properties"]`. Use `None` for fields you cannot find.

## Rules

1. Define `def extract(raw_data, schema, prompt):` -- this is mandatory.
2. Do NOT use `import` statements -- the following modules are pre-loaded in scope: \
   `json`, `re`, `math`, `datetime`, `decimal`, `collections`, `itertools`, \
   `functools`, `copy`, `string`, `textwrap`.
3. Do NOT use `open()`, `os`, `sys`, `subprocess`, `eval()`, `exec()`, or `__import__`.
4. Return ONLY valid Python code. No markdown fences, no explanation outside comments.
5. Handle missing data gracefully -- never crash, always return a dict.
6. Dates should be formatted as YYYY-MM-DD.
7. Currency amounts should be plain numbers (no symbols, no commas).
8. For arrays of objects, iterate table rows carefully.

## Strategy tips

- Start with keyValuePairs -- they often contain the most reliable field values.
- Use tables for line items / arrays.
- Fall back to regex on `raw_data["content"]` for fields not in KV pairs.
- Normalize strings: strip whitespace, handle encoding artifacts.
- For numbers: remove currency symbols and commas before converting.
"""

_INITIAL_USER = """\
## Target Schema

```json
{schema_json}
```

## Sample Document Intelligence Output

```
{di_sample}
```

Write the `extract(raw_data, schema, prompt)` function now. Return ONLY Python code."""


def build_initial_code_prompt(
    schema: dict, sample_di_output: str,
) -> tuple[str, str]:
    """
    Returns (system_prompt, user_message) for initial extraction code generation.

    Args:
        schema: Target JSON Schema.
        sample_di_output: Truncated DI output string.

    Returns:
        Tuple of (system_prompt, user_message).
    """
    schema_json = json.dumps(schema, indent=2)
    user_msg = _INITIAL_USER.format(
        schema_json=schema_json,
        di_sample=sample_di_output,
    )
    return (_INITIAL_SYSTEM, user_msg)


# ---------------------------------------------------------------------------
# Improvement prompt
# ---------------------------------------------------------------------------

_IMPROVE_SYSTEM = """\
You are an expert Python developer improving a document extraction function.

Your goal: fix the specific errors listed below to increase accuracy.

## Rules
1. Return the COMPLETE updated `extract(raw_data, schema, prompt)` function.
2. Do NOT use `import` statements -- modules are pre-loaded: \
   `json`, `re`, `math`, `datetime`, `decimal`, `collections`, `itertools`, \
   `functools`, `copy`, `string`, `textwrap`.
3. Do NOT use `open()`, `os`, `sys`, `subprocess`, `eval()`, `exec()`, or `__import__`.
4. Return ONLY valid Python code. No markdown fences, no explanation outside comments.
5. Focus on the failing fields. Do not break fields that already work.
6. Handle missing data gracefully -- never crash.
"""

_IMPROVE_USER = """\
## Iteration {iteration} -- Current accuracy: {accuracy:.1%}

## Error Summary (fields that are WRONG)

{error_summary}

## Current Code

```python
{current_code}
```

## Current Prompt

{current_prompt}

## Target Schema

```json
{schema_json}
```

## Sample Document Intelligence Output

```
{di_sample}
```

Fix the errors above. Return the COMPLETE updated `extract(raw_data, schema, prompt)` function."""


def build_improvement_prompt(
    current_code: str,
    current_prompt: str,
    schema: dict,
    error_summary: str,
    accuracy: float,
    iteration: int,
    sample_di_output: str,
) -> tuple[str, str]:
    """
    Returns (system_prompt, user_message) for improvement iterations.

    Args:
        current_code: Current extraction code.
        current_prompt: Current extraction prompt/hint.
        schema: Target JSON Schema.
        error_summary: Human-readable summary of wrong fields.
        accuracy: Current accuracy (0.0 to 1.0).
        iteration: Iteration number (1-based).
        sample_di_output: Truncated DI output string.

    Returns:
        Tuple of (system_prompt, user_message).
    """
    schema_json = json.dumps(schema, indent=2)
    user_msg = _IMPROVE_USER.format(
        iteration=iteration,
        accuracy=accuracy,
        error_summary=error_summary,
        current_code=current_code,
        current_prompt=current_prompt or "(none)",
        schema_json=schema_json,
        di_sample=sample_di_output,
    )
    return (_IMPROVE_SYSTEM, user_msg)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_claude_response(response_text: str) -> tuple[str, str]:
    """
    Parse Claude's response into (code, prompt).

    Handles:
    - Raw Python code (no fences)
    - Markdown-fenced Python blocks
    - JSON with "code" and "prompt" keys

    Returns:
        Tuple of (code, prompt). Prompt may be empty.
    """
    text = response_text.strip()

    # Try JSON parse first (Claude sometimes returns structured output)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            code = parsed.get("code", "")
            prompt = parsed.get("prompt", "")
            if code:
                return (code.strip(), prompt.strip())
    except (json.JSONDecodeError, TypeError):
        pass

    # Try JSON inside markdown fences
    json_fence = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
    if json_fence:
        try:
            parsed = json.loads(json_fence.group(1))
            if isinstance(parsed, dict) and parsed.get("code"):
                return (parsed["code"].strip(), parsed.get("prompt", "").strip())
        except (json.JSONDecodeError, TypeError):
            pass

    # Extract Python from markdown fences
    py_fence = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if py_fence:
        return (py_fence.group(1).strip(), "")

    # Assume entire response is code
    return (text, "")
