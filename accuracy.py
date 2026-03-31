"""Field-level accuracy calculation for extraction output vs ground truth."""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------

@dataclass
class FieldResult:
    field_name: str
    expected: object
    actual: object
    correct: bool
    field_type: str


@dataclass
class AccuracyResult:
    overall_accuracy: float
    total_fields: int
    correct_fields: int
    field_results: list[FieldResult] = field(default_factory=list)

    @property
    def error_summary(self) -> str:
        """Human-readable summary of wrong fields for Claude context."""
        errors = [f for f in self.field_results if not f.correct]
        if not errors:
            return "All fields correct."
        lines = []
        for fr in errors:
            lines.append(
                f"- {fr.field_name}: expected={fr.expected!r}, got={fr.actual!r}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Value comparison (type-aware, extracted from evaluate.py)
# ---------------------------------------------------------------------------

def _norm_str(s: str) -> str:
    """Normalize a string for comparison: lowercase, collapse whitespace."""
    return " ".join(s.lower().strip().split())


def compare_values(expected: object, actual: object, field_type: str = "string") -> bool:
    """
    Compare two values with type-aware logic.

    Handles:
    - None matching
    - Numbers with 0.01 tolerance
    - Strings with normalized whitespace/case
    - Arrays (element-wise recursive)
    - Objects (key-wise recursive)
    """
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
        return all(
            compare_values(e, a) for e, a in zip(expected, actual)
        )

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


# ---------------------------------------------------------------------------
# Single-document accuracy
# ---------------------------------------------------------------------------

def calculate_accuracy(
    extracted: dict, ground_truth: dict, schema: dict,
) -> AccuracyResult:
    """
    Calculate field-level accuracy of extraction against ground truth.

    Iterates over every field defined in schema["properties"], compares
    extracted[field] to ground_truth[field], and returns a detailed result.
    """
    properties = schema.get("properties", {})
    results: list[FieldResult] = []
    total = 0
    correct = 0

    for field_name, field_schema in properties.items():
        field_type = field_schema.get("type", "string")
        expected = ground_truth.get(field_name)
        actual = extracted.get(field_name)
        is_correct = compare_values(expected, actual, field_type)

        total += 1
        if is_correct:
            correct += 1

        results.append(FieldResult(
            field_name=field_name,
            expected=expected,
            actual=actual,
            correct=is_correct,
            field_type=field_type,
        ))

    overall = correct / total if total > 0 else 0.0

    return AccuracyResult(
        overall_accuracy=overall,
        total_fields=total,
        correct_fields=correct,
        field_results=results,
    )


# ---------------------------------------------------------------------------
# Multi-document accuracy
# ---------------------------------------------------------------------------

def calculate_multi_doc_accuracy(results: list[AccuracyResult]) -> float:
    """
    Aggregate accuracy across multiple documents.

    Uses micro-averaging: total correct fields / total fields.
    """
    total = sum(r.total_fields for r in results)
    correct = sum(r.correct_fields for r in results)
    return correct / total if total > 0 else 0.0
