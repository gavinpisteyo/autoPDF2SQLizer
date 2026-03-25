"""
Evaluation harness for autoPDF2SQLizer.
DO NOT MODIFY — this is the fixed accuracy measurement.

Runs the extraction pipeline (process.py) on every ground-truth document,
compares to the known-correct JSON, and prints accuracy metrics in a
grep-friendly format the Wiggum loop agent can parse.

Usage:
    uv run evaluate.py                  # full eval (extract + score)
    uv run evaluate.py --cache-only     # only run Azure Doc Intel and cache results
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from doc_intel import analyze_document, cache_result, get_cached_result
from process import extract

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
GROUND_TRUTH_DIR = BASE_DIR / "ground_truth"
SCHEMAS_DIR = BASE_DIR / "schemas"


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

def load_schema(doc_type: str) -> dict:
    """Load the JSON Schema for a document type."""
    for parent in [SCHEMAS_DIR, SCHEMAS_DIR / "custom"]:
        path = parent / f"{doc_type}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError(f"No schema for document type: {doc_type}")


# ---------------------------------------------------------------------------
# Ground-truth discovery
# ---------------------------------------------------------------------------

def find_ground_truth_documents() -> list[dict]:
    """
    Scan ground_truth/<doc_type>/<name>.pdf + <name>.json pairs.
    Returns list of dicts with doc_type, pdf_path, truth_path, name.
    """
    docs: list[dict] = []
    if not GROUND_TRUTH_DIR.exists():
        return docs

    for type_dir in sorted(GROUND_TRUTH_DIR.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith("."):
            continue
        doc_type = type_dir.name
        for pdf in sorted(type_dir.glob("*.pdf")):
            truth = pdf.with_suffix(".json")
            if truth.exists():
                docs.append({
                    "doc_type": doc_type,
                    "pdf_path": pdf,
                    "truth_path": truth,
                    "name": pdf.stem,
                })
    return docs


# ---------------------------------------------------------------------------
# Value comparison (type-aware)
# ---------------------------------------------------------------------------

def compare_values(expected, actual, field_type: str = "string") -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False

    if field_type == "number":
        try:
            return abs(float(expected) - float(actual)) < 0.01
        except (ValueError, TypeError):
            return _norm_str(str(expected)) == _norm_str(str(actual))

    if field_type == "array":
        if not isinstance(expected, list) or not isinstance(actual, list):
            return False
        if len(expected) != len(actual):
            return False
        return all(compare_values(e, a) for e, a in zip(expected, actual))

    if field_type == "object":
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            return False
        all_keys = set(expected) | set(actual)
        return all(
            compare_values(expected.get(k), actual.get(k))
            for k in all_keys
        )

    # Default: normalized string comparison
    return _norm_str(str(expected)) == _norm_str(str(actual))


def _norm_str(s: str) -> str:
    return " ".join(s.lower().strip().split())


# ---------------------------------------------------------------------------
# Single-document evaluation
# ---------------------------------------------------------------------------

def evaluate_document(doc: dict, schema: dict) -> dict | None:
    """Run extraction + comparison for one document. Returns field results."""

    raw = get_cached_result(doc["doc_type"], doc["name"])
    if raw is None:
        print(f"  SKIP {doc['name']} — no cached Doc Intel output. "
              f"Run: uv run evaluate.py --cache-only")
        return None

    with open(doc["truth_path"]) as f:
        truth = json.load(f)

    extracted = extract(raw, doc["doc_type"], schema)

    properties = schema.get("properties", {})
    field_results: dict[str, dict] = {}
    for field, field_schema in properties.items():
        exp = truth.get(field)
        act = extracted.get(field)
        correct = compare_values(exp, act, field_schema.get("type", "string"))
        field_results[field] = {
            "expected": exp,
            "actual": act,
            "correct": correct,
        }

    return field_results


# ---------------------------------------------------------------------------
# Full evaluation run
# ---------------------------------------------------------------------------

def run_evaluation():
    documents = find_ground_truth_documents()
    if not documents:
        print("No ground truth documents found.")
        print("Expected layout:")
        print("  ground_truth/<doc_type>/<name>.pdf")
        print("  ground_truth/<doc_type>/<name>.json")
        sys.exit(1)

    print(f"Found {len(documents)} ground truth document(s)\n")

    all_field_stats: dict[str, dict] = {}
    total_fields = 0
    total_correct = 0
    doc_count = 0

    for doc in documents:
        try:
            schema = load_schema(doc["doc_type"])
        except FileNotFoundError as e:
            print(f"  SKIP {doc['name']} — {e}")
            continue

        print(f"  [{doc['doc_type']}] {doc['name']}")
        results = evaluate_document(doc, schema)
        if results is None:
            continue

        doc_count += 1
        for field, r in results.items():
            total_fields += 1
            if r["correct"]:
                total_correct += 1

            key = f"{doc['doc_type']}.{field}"
            stats = all_field_stats.setdefault(key, {"total": 0, "correct": 0})
            stats["total"] += 1
            if r["correct"]:
                stats["correct"] += 1

            if not r["correct"]:
                print(f"    ✗ {field}: expected={r['expected']!r}  got={r['actual']!r}")

    # --- grep-friendly summary (matches program.md spec) ---
    accuracy = total_correct / total_fields if total_fields > 0 else 0.0

    field_acc = {
        k: v["correct"] / v["total"]
        for k, v in all_field_stats.items()
    }
    worst = sorted(field_acc.items(), key=lambda x: x[1])[:5]
    worst_str = ", ".join(
        f"{k} ({v * 100:.0f}%)" for k, v in worst if v < 1.0
    ) or "none"

    print("\n---")
    print(f"overall_accuracy:     {accuracy:.6f}")
    print(f"documents_processed:  {doc_count}")
    print(f"fields_evaluated:     {total_fields}")
    print(f"fields_correct:       {total_correct}")
    print(f"worst_fields:         {worst_str}")


# ---------------------------------------------------------------------------
# Cache-only mode  (run Doc Intel, save results, no extraction)
# ---------------------------------------------------------------------------

def cache_documents():
    documents = find_ground_truth_documents()
    if not documents:
        print("No ground truth documents found.")
        return

    for doc in documents:
        cached = get_cached_result(doc["doc_type"], doc["name"])
        if cached is not None:
            print(f"  CACHED  {doc['doc_type']}/{doc['name']}")
            continue

        print(f"  ANALYZE {doc['doc_type']}/{doc['name']}...")
        result = analyze_document(str(doc["pdf_path"]))
        out = cache_result(doc["doc_type"], doc["name"], result)
        print(f"          → {out}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="autoPDF2SQLizer evaluation")
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Only run Azure Doc Intel and cache results (no extraction/eval)",
    )
    args = parser.parse_args()

    if args.cache_only:
        cache_documents()
    else:
        t0 = time.time()
        run_evaluation()
        print(f"eval_time_seconds:    {time.time() - t0:.1f}")
