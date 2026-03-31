"""
Wiggum Trigger — GitHub API + git operations for launching Wiggum runs.
Commits ground truth data to a client branch and triggers the GitHub Actions workflow.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger("autopdf2sqlizer.wiggum_trigger")

GITHUB_PAT = os.getenv("GITHUB_PAT", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

GITHUB_API_BASE = "https://api.github.com"
WORKFLOW_FILE = "wiggum.yml"


class WiggumTriggerError(Exception):
    """Raised when a Wiggum trigger operation fails."""


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------

def is_github_configured() -> bool:
    """Check if GitHub PAT and repo are configured."""
    return bool(GITHUB_PAT and GITHUB_REPO)


def validate_config() -> None:
    """Ensure required environment variables are set."""
    if not GITHUB_PAT:
        raise WiggumTriggerError("GITHUB_PAT environment variable is not configured")
    if not GITHUB_REPO:
        raise WiggumTriggerError("GITHUB_REPO environment variable is not configured")


def _auth_headers() -> dict[str, str]:
    """Build GitHub API auth headers. Never logs the PAT."""
    return {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _clone_url() -> str:
    """Build the authenticated clone URL. Never logged directly."""
    return f"https://x-access-token:{GITHUB_PAT}@github.com/{GITHUB_REPO}.git"


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

def commit_ground_truth_to_branch(
    data_dir: str,
    branch: str,
    run_id: str,
) -> None:
    """
    Clone repo, checkout/create branch, copy ground truth + cache + schemas, commit, push.

    Args:
        data_dir: Path to the org/project data directory (e.g., data/{org_id}/{project_slug}/)
        branch: Git branch name (e.g., clients/acme-accounting)
        run_id: Internal run ID (used in commit message)
    """
    validate_config()
    data_path = Path(data_dir)

    if not data_path.exists():
        raise WiggumTriggerError(f"Data directory does not exist: {data_dir}")

    with tempfile.TemporaryDirectory(prefix="wiggum-") as tmp_dir:
        _clone_and_checkout(tmp_dir, branch)
        _copy_data_to_repo(data_path, tmp_dir)
        _commit_and_push(tmp_dir, branch, run_id)


def _clone_and_checkout(tmp_dir: str, branch: str) -> None:
    """Clone the repo and checkout (or create) the target branch."""
    clone_url = _clone_url()

    try:
        subprocess.run(
            ["git", "clone", clone_url, tmp_dir],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        # Sanitize clone errors to avoid leaking PAT
        stderr = (e.stderr or "").replace(GITHUB_PAT, "***") if GITHUB_PAT else (e.stderr or "")
        raise WiggumTriggerError(f"Git clone failed: {stderr}") from e

    # Try to checkout existing remote branch; if it doesn't exist, create from main
    fetch_result = subprocess.run(
        ["git", "fetch", "origin", branch],
        cwd=tmp_dir,
        capture_output=True,
        text=True,
    )

    if fetch_result.returncode == 0:
        # Remote branch exists — check it out
        try:
            subprocess.run(
                ["git", "checkout", branch],
                cwd=tmp_dir,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").replace(GITHUB_PAT, "***") if GITHUB_PAT else (e.stderr or "")
            raise WiggumTriggerError(f"Failed to checkout branch '{branch}': {stderr}") from e
    else:
        logger.info("Branch '%s' does not exist remotely, creating from main", branch)
        try:
            subprocess.run(
                ["git", "checkout", "-b", branch],
                cwd=tmp_dir,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").replace(GITHUB_PAT, "***") if GITHUB_PAT else (e.stderr or "")
            raise WiggumTriggerError(f"Failed to create branch '{branch}': {stderr}") from e


def _copy_data_to_repo(data_path: Path, tmp_dir: str) -> None:
    """Copy ground_truth/, cache/, and schemas/custom/ from data_dir into the repo."""
    repo_path = Path(tmp_dir)

    dirs_to_copy = [
        ("ground_truth", "ground_truth"),
        ("cache", "cache"),
        ("schemas/custom", "schemas/custom"),
    ]

    for src_rel, dst_rel in dirs_to_copy:
        src = data_path / src_rel
        dst = repo_path / dst_rel
        if src.exists() and src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            logger.info("Copied %s -> %s", src_rel, dst_rel)


def _commit_and_push(tmp_dir: str, branch: str, run_id: str) -> None:
    """Stage all changes, commit, and push."""
    _run_git(tmp_dir, ["git", "config", "user.name", "Wiggum Bot"])
    _run_git(tmp_dir, ["git", "config", "user.email", "wiggum@autopdf2sqlizer.com"])
    _run_git(tmp_dir, ["git", "add", "-A"])

    # Check if there are changes to commit
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_dir,
        capture_output=True,
        text=True,
    )
    if not status_result.stdout.strip():
        logger.info("No changes to commit for run %s", run_id)
        return

    _run_git(tmp_dir, ["git", "commit", "-m", f"Add ground truth for run {run_id}"])
    _run_git(tmp_dir, ["git", "push", "origin", branch])


def _run_git(cwd: str, cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a git command, raising WiggumTriggerError on failure."""
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        # Sanitize error output to avoid leaking PAT
        stderr = e.stderr or ""
        sanitized = stderr.replace(GITHUB_PAT, "***") if GITHUB_PAT else stderr
        raise WiggumTriggerError(f"Git command failed ({cmd[1]}): {sanitized}") from e


# ---------------------------------------------------------------------------
# GitHub Actions API
# ---------------------------------------------------------------------------

def trigger_workflow(
    branch: str,
    cycles: int,
    experiments: int,
    model: str,
    org_id: str,
    project_id: str,
    run_id: str,
) -> None:
    """Trigger wiggum.yml via workflow_dispatch."""
    validate_config()

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    payload = {
        "ref": branch,
        "inputs": {
            "branch": branch,
            "cycles": str(cycles),
            "experiments": str(experiments),
            "model": model,
            "org_id": org_id,
            "project_id": project_id,
            "run_id": run_id,
        },
    }

    response = httpx.post(url, json=payload, headers=_auth_headers(), timeout=30)

    if response.status_code not in (204, 200):
        raise WiggumTriggerError(
            f"Failed to trigger workflow: {response.status_code} {response.text}"
        )

    logger.info("Triggered workflow on branch '%s' for run %s", branch, run_id)


def find_triggered_run(
    branch: str,
    run_id: str,
    after: str,
) -> int | None:
    """
    Find the GitHub Actions run triggered by our dispatch.

    Args:
        branch: Branch the workflow was triggered on
        run_id: Our internal run ID (passed as input to workflow)
        after: ISO timestamp — only consider runs created after this time

    Returns:
        The github_run_id if found, None otherwise.
    """
    validate_config()

    url = (
        f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/actions/runs"
        f"?branch={branch}&event=workflow_dispatch&created=>{after}&per_page=10"
    )

    response = httpx.get(url, headers=_auth_headers(), timeout=30)

    if response.status_code != 200:
        logger.warning("Failed to list workflow runs: %s %s", response.status_code, response.text)
        return None

    data = response.json()
    runs = data.get("workflow_runs", [])

    for run in runs:
        # The most recently triggered run on this branch is likely ours
        # GitHub doesn't expose inputs directly on the runs list,
        # so we match by branch + timing
        return run.get("id")

    return None


def get_workflow_run_status(github_run_id: int) -> dict:
    """
    Get the status of a GitHub Actions run.

    Returns:
        Dict with keys: status, conclusion, html_url
    """
    validate_config()

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/actions/runs/{github_run_id}"
    response = httpx.get(url, headers=_auth_headers(), timeout=30)

    if response.status_code != 200:
        raise WiggumTriggerError(
            f"Failed to get workflow run status: {response.status_code} {response.text}"
        )

    data = response.json()
    return {
        "status": data.get("status", "unknown"),
        "conclusion": data.get("conclusion"),
        "html_url": data.get("html_url", ""),
    }
