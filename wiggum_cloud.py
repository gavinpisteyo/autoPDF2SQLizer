"""
Wiggum Cloud — API-driven autonomous extraction optimizer.
============================================================
Runs the Wiggum loop using Claude API calls instead of Claude Code CLI.
Each API call is inherently a fresh agent — no context carryover.
Runs anywhere Python runs: locally, GitHub Actions, Azure Functions, etc.

Usage:
    uv run wiggum_cloud.py                          # run forever
    uv run wiggum_cloud.py --cycles 10              # run 10 cycles
    uv run wiggum_cloud.py --model claude-opus-4-6  # use Opus
    uv run wiggum_cloud.py --experiments 3           # 3 experiments per cycle
"""

import argparse
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
MODIFIABLE_FILES = ["process.py"]
MODIFIABLE_DIRS = ["prompts"]
READONLY_CONTEXT = ["evaluate.py", "doc_intel.py", "sql_gen.py"]
SCHEMAS_DIR = BASE_DIR / "schemas"

SYSTEM_PROMPT = """You are an autonomous PDF extraction accuracy optimizer.

YOUR GOAL: Improve the overall_accuracy metric by modifying the extraction code.

YOU WILL RECEIVE:
1. The current process.py (the main file you modify)
2. The current extraction prompts (in prompts/)
3. Evaluation results showing which fields are failing and why
4. The schemas defining expected output fields

RESPOND WITH modified files using this exact format:

<file path="process.py">
...complete file content here...
</file>

<file path="prompts/invoice.md">
...complete file content here...
</file>

RULES:
- Only modify process.py and files in prompts/
- Include the COMPLETE file content for any file you change
- Only include files you actually changed
- Focus on the worst_fields first — biggest accuracy gains
- Look at the expected vs actual values to understand WHY fields are wrong
- Common fixes: date format normalization, number cleaning, better LLM prompts,
  field location hints, regex post-processing, conditional logic per doc type
- Keep code clean: type hints, clear function names, handle errors
- Simpler is better — don't add complexity unless it clearly improves accuracy
- If accuracy is already at 1.0, try to simplify the code while keeping 100%

STRATEGY:
- Dates wrong? → Add format normalization in post_process
- Numbers have symbols? → Improve _normalize_number
- Field is null? → The LLM prompt may not know where to look
- Address truncated? → Check if pre_process is losing data
- Deterministic rules beat LLM judgment for structured fields
"""


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

@dataclass
class FileChange:
    path: str
    content: str


def read_current_state() -> dict:
    """Read all relevant files into a dict."""
    state = {}

    # Modifiable files
    for name in MODIFIABLE_FILES:
        path = BASE_DIR / name
        if path.exists():
            state[name] = path.read_text()

    # Modifiable directories
    for dirname in MODIFIABLE_DIRS:
        dirpath = BASE_DIR / dirname
        if dirpath.exists():
            for f in sorted(dirpath.glob("*")):
                if f.is_file():
                    rel = f"{dirname}/{f.name}"
                    state[rel] = f.read_text()

    # Schemas (read-only context)
    if SCHEMAS_DIR.exists():
        for f in sorted(SCHEMAS_DIR.glob("*.json")):
            state[f"schemas/{f.name}"] = f.read_text()
        custom = SCHEMAS_DIR / "custom"
        if custom.exists():
            for f in sorted(custom.glob("*.json")):
                state[f"schemas/custom/{f.name}"] = f.read_text()

    return state


def apply_changes(changes: list[FileChange]):
    """Write modified files to disk."""
    for change in changes:
        path = BASE_DIR / change.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(change.content)


def parse_file_changes(response_text: str) -> list[FileChange]:
    """Parse <file path="...">...</file> blocks from Claude's response."""
    changes = []
    pattern = r'<file\s+path="([^"]+)">\s*\n?(.*?)\n?\s*</file>'
    for match in re.finditer(pattern, response_text, re.DOTALL):
        path = match.group(1)
        content = match.group(2)
        # Only allow modifiable paths
        if path in MODIFIABLE_FILES or any(path.startswith(d + "/") for d in MODIFIABLE_DIRS):
            changes.append(FileChange(path=path, content=content))
    return changes


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass
class EvalResult:
    accuracy: float
    fields_evaluated: int
    fields_correct: int
    worst_fields: str
    full_output: str
    success: bool


def run_eval() -> EvalResult:
    """Run evaluate.py and parse results."""
    try:
        result = subprocess.run(
            ["uv", "run", "evaluate.py"],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            timeout=300,
        )
        output = result.stdout + result.stderr

        accuracy = 0.0
        fields_evaluated = 0
        fields_correct = 0
        worst_fields = ""

        for line in output.split("\n"):
            if line.startswith("overall_accuracy:"):
                accuracy = float(line.split()[-1])
            elif line.startswith("fields_evaluated:"):
                fields_evaluated = int(line.split()[-1])
            elif line.startswith("fields_correct:"):
                fields_correct = int(line.split()[-1])
            elif line.startswith("worst_fields:"):
                worst_fields = line.split(":", 1)[-1].strip()

        return EvalResult(
            accuracy=accuracy,
            fields_evaluated=fields_evaluated,
            fields_correct=fields_correct,
            worst_fields=worst_fields,
            full_output=output,
            success=result.returncode == 0,
        )
    except subprocess.TimeoutExpired:
        return EvalResult(0.0, 0, 0, "", "TIMEOUT", False)
    except Exception as e:
        return EvalResult(0.0, 0, 0, "", str(e), False)


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

def git_commit(message: str):
    subprocess.run(["git", "add", "-A"], cwd=str(BASE_DIR), check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(BASE_DIR),
        check=True,
        capture_output=True,
    )


def git_reset():
    subprocess.run(
        ["git", "reset", "--hard", "HEAD~1"],
        cwd=str(BASE_DIR),
        check=True,
        capture_output=True,
    )


def git_short_hash() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Results logging
# ---------------------------------------------------------------------------

def log_result(commit: str, accuracy: float, status: str, description: str):
    tsv_path = BASE_DIR / "results.tsv"
    if not tsv_path.exists():
        tsv_path.write_text("commit\taccuracy\tstatus\tdescription\n")
    with open(tsv_path, "a") as f:
        f.write(f"{commit}\t{accuracy:.6f}\t{status}\t{description}\n")


# ---------------------------------------------------------------------------
# The Wiggum Cloud loop
# ---------------------------------------------------------------------------

def run_cycle(
    client: Anthropic,
    model: str,
    experiments: int,
    cycle_num: int,
) -> float:
    """Run one cycle: eval → propose → apply → eval → keep/discard. Returns final accuracy."""

    # Get baseline
    print(f"\n  Running baseline evaluation...")
    baseline = run_eval()
    if not baseline.success:
        print(f"  Eval failed: {baseline.full_output[:200]}")
        return 0.0

    print(f"  Baseline accuracy: {baseline.accuracy:.6f}")
    print(f"  Worst fields: {baseline.worst_fields}")
    current_accuracy = baseline.accuracy

    for exp in range(experiments):
        print(f"\n  --- Experiment {exp + 1}/{experiments} ---")

        # Read current state
        state = read_current_state()

        # Build the user message with current code + eval results
        user_parts = ["Here is the current state of the extraction code:\n"]

        for path, content in sorted(state.items()):
            user_parts.append(f'<file path="{path}">\n{content}\n</file>\n')

        user_parts.append(f"\nEVALUATION RESULTS:\n{baseline.full_output}\n")
        user_parts.append(f"\nCurrent accuracy: {current_accuracy:.6f}")
        user_parts.append(f"Worst fields: {baseline.worst_fields}")
        user_parts.append(
            "\nPropose changes to improve accuracy. "
            "Return modified files using <file path=\"...\">...</file> format."
        )

        user_message = "\n".join(user_parts)

        # Call Claude API — fresh instance, no history
        print(f"  Calling {model}...")
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8192,
                temperature=0.3,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            response_text = response.content[0].text
        except Exception as e:
            print(f"  API error: {e}")
            continue

        # Parse file changes
        changes = parse_file_changes(response_text)
        if not changes:
            print(f"  No file changes proposed. Skipping.")
            continue

        print(f"  Changes proposed: {[c.path for c in changes]}")

        # Apply changes and commit
        apply_changes(changes)
        description = _extract_description(response_text)
        git_commit(f"wiggum: {description}")
        commit_hash = git_short_hash()

        # Evaluate
        print(f"  Running evaluation...")
        result = run_eval()

        if not result.success:
            print(f"  Eval crashed. Reverting.")
            git_reset()
            log_result(commit_hash, 0.0, "crash", description)
            continue

        print(f"  Accuracy: {current_accuracy:.6f} → {result.accuracy:.6f}")

        if result.accuracy > current_accuracy:
            # Keep — accuracy improved
            print(f"  KEEP (+{result.accuracy - current_accuracy:.6f})")
            log_result(commit_hash, result.accuracy, "keep", description)
            current_accuracy = result.accuracy
            baseline = result  # update baseline for next experiment
        else:
            # Discard — same or worse
            print(f"  DISCARD")
            git_reset()
            log_result(commit_hash, result.accuracy, "discard", description)

        if current_accuracy >= 1.0:
            print(f"\n  100% accuracy reached!")
            break

    return current_accuracy


def _extract_description(response_text: str) -> str:
    """Try to extract a short description from Claude's response."""
    # Look for text before the first <file> tag
    before_files = response_text.split("<file")[0].strip()
    # Take the last non-empty line as the description
    lines = [l.strip() for l in before_files.split("\n") if l.strip()]
    if lines:
        desc = lines[-1][:100]
        # Clean up markdown artifacts
        desc = re.sub(r"[*#`]", "", desc).strip()
        return desc or "wiggum optimization"
    return "wiggum optimization"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Wiggum Cloud — API-driven optimization loop")
    parser.add_argument("--cycles", type=int, default=0, help="Max cycles (0 = infinite)")
    parser.add_argument("--experiments", type=int, default=5, help="Experiments per cycle")
    parser.add_argument("--model", default="claude-sonnet-4-20250514", help="Claude model to use")
    args = parser.parse_args()

    client = Anthropic()

    print("========================================")
    print("  Wiggum Cloud — autoPDF2SQLizer")
    print("========================================")
    print(f"  Model: {args.model}")
    print(f"  Experiments per cycle: {args.experiments}")
    print(f"  Max cycles: {'infinite' if args.cycles == 0 else args.cycles}")
    print("========================================")

    cycle = 0
    while True:
        cycle += 1
        if args.cycles > 0 and cycle > args.cycles:
            print(f"\nReached {args.cycles} cycles. Stopping.")
            break

        print(f"\n{'='*40}")
        print(f"  Cycle {cycle} — {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*40}")

        accuracy = run_cycle(client, args.model, args.experiments, cycle)
        print(f"\n  Cycle {cycle} complete. Accuracy: {accuracy:.6f}")

        if accuracy >= 1.0:
            print("\n  Target accuracy reached. Stopping.")
            break


if __name__ == "__main__":
    main()
