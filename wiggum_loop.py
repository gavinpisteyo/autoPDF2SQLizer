"""
Server-side Wiggum loop -- iteratively improves extraction code until 100% accuracy.

The loop:
1. Load ground truth + cached DI output
2. Generate initial extraction code (or use existing)
3. For each iteration:
   a. Execute code in sandbox against all ground truth docs
   b. Calculate field-level accuracy
   c. If 100% -> done
   d. If improved -> save as new best
   e. Ask Claude to improve based on errors
   f. Repeat
4. Save best version, update run status
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic

import extraction_code_db as code_db
import metadata as db
from accuracy import AccuracyResult, calculate_accuracy, calculate_multi_doc_accuracy
from auth.dependencies import DATA_DIR, GLOBAL_SCHEMAS_DIR, PERSISTENT_ROOT
from sandbox import SandboxExecutionError, execute_extraction
from wiggum_prompts import (
    build_improvement_prompt,
    build_initial_code_prompt,
    parse_claude_response,
    truncate_di_output,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GroundTruthDoc:
    name: str
    truth: dict
    raw_di: dict


@dataclass(frozen=True)
class LoopResult:
    best_accuracy: float
    iterations_run: int
    final_version: int
    accuracy_history: list[float]


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ProjectPaths:
    """Resolved filesystem paths for a project."""
    project_dir: Path
    custom_schemas: Path
    ground_truth: Path
    cache: Path


def _resolve_paths(org_id: str, project_id: str) -> _ProjectPaths:
    """
    Resolve data paths for an org+project using PERSISTENT_ROOT.

    Layout:
        {PERSISTENT_ROOT}/data/{org_id}/{project_slug}/ground_truth/{doc_type}/
        {PERSISTENT_ROOT}/data/{org_id}/{project_slug}/cache/{doc_type}/
        {PERSISTENT_ROOT}/data/{org_id}/{project_slug}/schemas/custom/
    """
    project = db.get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")

    project_dir = DATA_DIR / org_id / project.slug
    return _ProjectPaths(
        project_dir=project_dir,
        custom_schemas=project_dir / "schemas" / "custom",
        ground_truth=project_dir / "ground_truth",
        cache=project_dir / "cache",
    )


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

def _load_schema(paths: _ProjectPaths, doc_type: str) -> dict:
    """
    Load the JSON schema for a document type.

    Checks project-level custom schemas first, then global schemas.
    Raises ValueError if no schema is found.
    """
    custom_path = paths.custom_schemas / f"{doc_type}.json"
    if custom_path.exists():
        return json.loads(custom_path.read_text())

    global_path = GLOBAL_SCHEMAS_DIR / f"{doc_type}.json"
    if global_path.exists():
        return json.loads(global_path.read_text())

    raise ValueError(
        f"No schema found for doc_type={doc_type!r}. "
        f"Checked: {custom_path}, {global_path}"
    )


# ---------------------------------------------------------------------------
# Ground truth loading
# ---------------------------------------------------------------------------

def _load_ground_truth(paths: _ProjectPaths, doc_type: str) -> list[GroundTruthDoc]:
    """
    Scan the ground_truth directory for JSON files and match each with its
    cached DI output.

    Expected layout:
        ground_truth/{doc_type}/{name}.json   (ground truth values)
        cache/{doc_type}/{name}.raw.json      (cached DI output)

    Skips documents without a cached DI result (they need caching first).
    """
    gt_dir = paths.ground_truth / doc_type
    if not gt_dir.exists():
        return []

    cache_dir = paths.cache / doc_type
    docs: list[GroundTruthDoc] = []

    for truth_path in sorted(gt_dir.glob("*.json")):
        name = truth_path.stem
        cache_path = cache_dir / f"{name}.raw.json"

        if not cache_path.exists():
            logger.warning(
                "Skipping ground truth doc %s -- no cached DI output at %s",
                name, cache_path,
            )
            continue

        truth = json.loads(truth_path.read_text())
        raw_di = json.loads(cache_path.read_text())
        docs.append(GroundTruthDoc(name=name, truth=truth, raw_di=raw_di))

    return docs


# ---------------------------------------------------------------------------
# Claude API calls
# ---------------------------------------------------------------------------

def _call_claude_initial(
    client: Anthropic,
    schema: dict,
    sample_di: str,
    model: str,
) -> tuple[str, str]:
    """
    Call Claude to generate initial extraction code.

    Returns (code, prompt) tuple.
    """
    system_prompt, user_message = build_initial_code_prompt(schema, sample_di)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0.0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    response_text = response.content[0].text
    code, prompt = parse_claude_response(response_text)

    if not code.strip():
        raise ValueError("Claude returned empty code for initial generation")

    return (code, prompt)


def _call_claude_improve(
    client: Anthropic,
    code: str,
    prompt: str,
    schema: dict,
    errors: str,
    accuracy: float,
    iteration: int,
    sample_di: str,
    model: str,
) -> tuple[str, str]:
    """
    Call Claude to improve extraction code based on error feedback.

    Returns (improved_code, improved_prompt) tuple.
    """
    system_prompt, user_message = build_improvement_prompt(
        current_code=code,
        current_prompt=prompt,
        schema=schema,
        error_summary=errors,
        accuracy=accuracy,
        iteration=iteration,
        sample_di_output=sample_di,
    )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0.0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    response_text = response.content[0].text
    new_code, new_prompt = parse_claude_response(response_text)

    if not new_code.strip():
        logger.warning("Claude returned empty code at iteration %d, keeping current", iteration)
        return (code, prompt)

    return (new_code, new_prompt or prompt)


# ---------------------------------------------------------------------------
# Error summary
# ---------------------------------------------------------------------------

def _build_error_summary(
    results: list[AccuracyResult],
    docs: list[GroundTruthDoc],
) -> str:
    """
    Combine per-document error summaries into a single string for Claude context.

    Format:
        ## Document: invoice-001 (accuracy: 80.0%)
        - field_x: expected='A', got='B'
        ...
    """
    lines: list[str] = []

    for result, doc in zip(results, docs):
        accuracy_pct = result.overall_accuracy * 100
        lines.append(f"## Document: {doc.name} (accuracy: {accuracy_pct:.1f}%)")

        error_text = result.error_summary
        if error_text == "All fields correct.":
            lines.append("All fields correct.")
        else:
            lines.append(error_text)

        lines.append("")  # blank separator

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop(
    org_id: str,
    project_id: str,
    run_id: str,
    max_iterations: int = 20,
    model: str = "claude-sonnet-4-20250514",
) -> LoopResult:
    """
    Main entry point. Runs the full optimization loop.
    Called from a background thread -- this is a blocking function.
    """
    client = Anthropic()

    # Update run status
    db.update_wiggum_run(run_id, status="in_progress")

    try:
        # Load inputs
        paths = _resolve_paths(org_id, project_id)
        project = db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        doc_type = project.slug
        schema = _load_schema(paths, doc_type)
        gt_docs = _load_ground_truth(paths, doc_type)

        if not gt_docs:
            raise ValueError("No ground truth documents found")

        # Get or generate initial extraction code
        current = code_db.get_extraction_code(project_id)
        if current:
            code = current.processing_code
            prompt = current.prompt
            version = current.version
        else:
            # Generate initial code
            sample_di = truncate_di_output(gt_docs[0].raw_di)
            code, prompt = _call_claude_initial(client, schema, sample_di, model)
            version = 1
            code_db.save_extraction_code(project_id, prompt, code, 0.0, version)
            code_db.save_extraction_version(project_id, prompt, code, 0.0, version)

        best_accuracy = 0.0
        best_code = code
        best_prompt = prompt
        best_version = version
        accuracy_history: list[float] = []

        for iteration in range(1, max_iterations + 1):
            logger.info("Wiggum run %s iteration %d/%d", run_id, iteration, max_iterations)

            # Execute against all ground truth docs
            results: list[AccuracyResult] = []
            for doc in gt_docs:
                try:
                    extracted = execute_extraction(code, prompt, doc.raw_di, schema)
                    result = calculate_accuracy(extracted, doc.truth, schema)
                    results.append(result)
                except SandboxExecutionError as exc:
                    logger.warning("Sandbox error on %s: %s", doc.name, exc)
                    # Score as 0% for this doc
                    results.append(AccuracyResult(
                        overall_accuracy=0.0,
                        total_fields=1,
                        correct_fields=0,
                        field_results=[],
                    ))

            accuracy = calculate_multi_doc_accuracy(results)
            accuracy_history.append(accuracy)
            logger.info("Iteration %d accuracy: %.1f%%", iteration, accuracy * 100)

            # Update run with latest accuracy
            db.update_wiggum_run(
                run_id,
                best_accuracy=max(best_accuracy, accuracy),
                accuracy_history=json.dumps(accuracy_history),
            )

            # Check if we hit 100%
            if accuracy >= 1.0:
                logger.info("100%% accuracy achieved at iteration %d!", iteration)
                best_accuracy = accuracy
                best_code = code
                best_prompt = prompt
                best_version = version + iteration
                break

            # Keep if improved
            if accuracy > best_accuracy:
                best_accuracy = accuracy
                best_code = code
                best_prompt = prompt
                best_version = version + iteration
                code_db.save_extraction_code(
                    project_id, prompt, code, accuracy, best_version,
                )
                code_db.save_extraction_version(
                    project_id, prompt, code, accuracy, best_version,
                )
                logger.info(
                    "New best: %.1f%% (version %d)", accuracy * 100, best_version,
                )
            else:
                # Save to version history anyway (for audit) but don't update current best
                code_db.save_extraction_version(
                    project_id, prompt, code, accuracy, version + iteration,
                )

            # Ask Claude to improve
            error_summary = _build_error_summary(results, gt_docs)
            sample_di = truncate_di_output(gt_docs[0].raw_di)

            try:
                code, prompt = _call_claude_improve(
                    client, code, prompt, schema, error_summary,
                    accuracy, iteration, sample_di, model,
                )
            except Exception as exc:
                logger.error("Claude API failed at iteration %d: %s", iteration, exc)
                # Stop iterating -- use current best
                break

        # Save final best
        code_db.save_extraction_code(
            project_id, best_prompt, best_code, best_accuracy, best_version,
        )

        # Update run as completed
        db.update_wiggum_run(
            run_id,
            status="completed",
            best_accuracy=best_accuracy,
            accuracy_history=json.dumps(accuracy_history),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        return LoopResult(
            best_accuracy=best_accuracy,
            iterations_run=len(accuracy_history),
            final_version=best_version,
            accuracy_history=accuracy_history,
        )

    except Exception as exc:
        logger.error("Wiggum loop failed for run %s: %s", run_id, exc, exc_info=True)
        db.update_wiggum_run(
            run_id,
            status="failed",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        raise
