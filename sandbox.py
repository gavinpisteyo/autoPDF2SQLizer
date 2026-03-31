"""Sandbox for executing LLM-generated extraction code safely."""
from __future__ import annotations

import collections
import copy
import datetime
import decimal
import functools
import itertools
import json
import math
import re
import string
import textwrap
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SandboxExecutionError(Exception):
    """Base exception for sandbox execution failures."""


class SandboxTimeoutError(SandboxExecutionError):
    """Raised when code execution exceeds the timeout."""


class SandboxValidationError(SandboxExecutionError):
    """Raised when code fails safety validation or produces invalid output."""


# ---------------------------------------------------------------------------
# Safe builtins and modules
# ---------------------------------------------------------------------------

SAFE_BUILTINS: dict = {
    # Core functions
    "len": len, "range": range, "enumerate": enumerate, "zip": zip,
    "map": map, "filter": filter, "sorted": sorted, "reversed": reversed,
    "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
    # Type constructors
    "int": int, "float": float, "str": str, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set, "frozenset": frozenset,
    # Type checks
    "type": type, "isinstance": isinstance, "issubclass": issubclass,
    "hasattr": hasattr, "getattr": getattr, "setattr": setattr,
    # I/O & display
    "print": print, "repr": repr, "hash": hash, "id": id,
    # Encoding
    "chr": chr, "ord": ord, "hex": hex, "oct": oct, "bin": bin,
    # Iterators
    "all": all, "any": any, "iter": iter, "next": next,
    # Exceptions
    "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
    "IndexError": IndexError, "AttributeError": AttributeError,
    "StopIteration": StopIteration, "Exception": Exception,
    # Constants
    "None": None, "True": True, "False": False,
}

SAFE_MODULES: dict = {
    "json": json,
    "re": re,
    "math": math,
    "datetime": datetime,
    "decimal": decimal,
    "collections": collections,
    "itertools": itertools,
    "functools": functools,
    "copy": copy,
    "string": string,
    "textwrap": textwrap,
}

DANGEROUS_PATTERNS: list[str] = [
    "__import__", "__subclasses__", "__bases__", "__globals__", "__builtins__",
    "__code__", "__reduce__", "os.", "sys.", "subprocess", "open(",
    "eval(", "exec(", "compile(", "breakpoint", "exit(", "quit(",
]

# Regex to catch bare import/from-import statements
_IMPORT_RE = re.compile(r"^\s*(import|from)\s+\w+", re.MULTILINE)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_code_safety(code: str) -> None:
    """Reject code containing dangerous patterns or import statements."""
    for pattern in DANGEROUS_PATTERNS:
        if pattern in code:
            raise SandboxValidationError(
                f"Code contains forbidden pattern: {pattern}"
            )
    if _IMPORT_RE.search(code):
        raise SandboxValidationError(
            "Code contains forbidden import statement. "
            "Use pre-loaded modules: json, re, math, datetime, decimal, "
            "collections, itertools, functools, copy, string, textwrap."
        )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute_extraction(
    code: str,
    prompt: str,
    raw_di_json: dict,
    schema: dict,
    timeout_seconds: int = 30,
) -> dict:
    """
    Execute extraction code in a restricted sandbox.

    The code must either:
    - Assign a ``result`` dict variable, or
    - Define ``extract(raw_data, schema, prompt)`` returning a dict.

    Args:
        code: LLM-generated Python extraction code.
        prompt: Natural-language extraction guidance.
        raw_di_json: Raw Azure Document Intelligence output.
        schema: Target JSON Schema.
        timeout_seconds: Maximum execution time.

    Returns:
        Extracted data dict.

    Raises:
        SandboxValidationError: Unsafe code or invalid output.
        SandboxTimeoutError: Execution exceeded timeout.
        SandboxExecutionError: Any other execution failure.
    """
    _validate_code_safety(code)

    # Deep copy inputs for immutability
    raw_copy = copy.deepcopy(raw_di_json)
    schema_copy = copy.deepcopy(schema)

    sandbox_globals: dict = {
        "__builtins__": SAFE_BUILTINS,
        **SAFE_MODULES,
    }
    sandbox_locals: dict = {
        "raw_data": raw_copy,
        "schema": schema_copy,
        "prompt": prompt,
    }

    def _run() -> dict:
        exec(code, sandbox_globals, sandbox_locals)  # noqa: S102

        # Option 1: code set a `result` dict directly
        if "result" in sandbox_locals and isinstance(sandbox_locals["result"], dict):
            return sandbox_locals["result"]

        # Option 2: code defined an `extract` function
        if "extract" in sandbox_locals and callable(sandbox_locals["extract"]):
            output = sandbox_locals["extract"](raw_copy, schema_copy, prompt)
            if not isinstance(output, dict):
                raise SandboxValidationError(
                    f"extract() returned {type(output).__name__}, expected dict"
                )
            return output

        raise SandboxValidationError(
            "Code must define 'result' dict or "
            "'extract(raw_data, schema, prompt)' function"
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeout:
            raise SandboxTimeoutError(
                f"Code execution exceeded {timeout_seconds}s timeout"
            )
        except SandboxExecutionError:
            raise
        except Exception as exc:
            raise SandboxExecutionError(f"Code execution failed: {exc}")
