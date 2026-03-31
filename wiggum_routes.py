"""
Wiggum Routes — FastAPI endpoints for triggering and monitoring Wiggum optimization runs.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, Header, HTTPException

from auth import OrgContext, OrgRole, get_org_context
from auth.models import role_at_least
import metadata as db
import wiggum_trigger as trigger

logger = logging.getLogger("autopdf2sqlizer.wiggum_routes")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

router = APIRouter(prefix="/api/wiggum", tags=["wiggum"])

ACTIVE_STATUSES = {"pending", "queued", "in_progress"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_project(ctx: OrgContext, x_project_id: str) -> db.Project | None:
    """Resolve and validate the project from the header. Returns None if no header."""
    if not x_project_id:
        return None

    project = db.get_project(x_project_id)
    if not project or project.org_id != ctx.org_id:
        raise HTTPException(404, "Project not found")

    if ctx.role != OrgRole.ORG_ADMIN and not db.is_project_member(x_project_id, ctx.user.sub):
        raise HTTPException(403, "Not a member of this project")

    return project


def _build_branch_name(org_name: str, project_slug: str) -> str:
    """Generate a git branch name from org name + project slug."""
    clean_org = re.sub(r"[^\w\-]", "-", org_name.lower().strip())
    return f"clients/{clean_org}-{project_slug}"


def _build_data_dir(org_id: str, project_slug: str) -> str:
    """Build the path to the org/project data directory."""
    return str(DATA_DIR / org_id / project_slug)


def _has_ground_truth(data_dir: str) -> bool:
    """Check that ground truth data exists in the data directory."""
    gt_path = Path(data_dir) / "ground_truth"
    if not gt_path.exists():
        return False
    # At least one PDF must exist
    return any(gt_path.rglob("*.pdf"))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/start")
async def start_wiggum(
    cycles: int = Form(default=5),
    experiments: int = Form(default=5),
    model: str = Form(default="claude-sonnet-4-20250514"),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Start a Wiggum optimization run."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.DEVELOPER):
        raise HTTPException(403, f"Requires {OrgRole.DEVELOPER.value}, you have {ctx.role.value}")

    # Validate GitHub configuration
    try:
        trigger.validate_config()
    except trigger.WiggumTriggerError as e:
        raise HTTPException(503, f"Wiggum is not configured: {e}")

    # Resolve project
    project = _resolve_project(ctx, x_project_id)
    if not project:
        raise HTTPException(400, "x-project-id header is required to start Wiggum")

    # Check no active run exists for this org+project
    latest = db.get_latest_wiggum_run(ctx.org_id, project.id)
    if latest and latest.status in ACTIVE_STATUSES:
        raise HTTPException(
            409,
            f"An active Wiggum run already exists (id={latest.id}, status={latest.status})",
        )

    # Validate ground truth exists
    data_dir = _build_data_dir(ctx.org_id, project.slug)
    if not _has_ground_truth(data_dir):
        raise HTTPException(
            400,
            "No ground truth data found. Upload ground truth PDFs before starting Wiggum.",
        )

    # Resolve org name for branch naming
    org = db.get_org(ctx.org_id)
    org_name = org.name if org else ctx.org_id

    # Generate branch and run ID
    branch = _build_branch_name(org_name, project.slug)
    run_id = str(uuid.uuid4())

    # Create DB record
    run = db.create_wiggum_run(
        id=run_id,
        org_id=ctx.org_id,
        project_id=project.id,
        branch=branch,
        cycles=cycles,
        experiments=experiments,
        model=model,
    )

    # Commit ground truth to branch
    try:
        trigger.commit_ground_truth_to_branch(data_dir, branch, run_id)
    except trigger.WiggumTriggerError as e:
        db.update_wiggum_run(run_id, status="failed")
        logger.error("Failed to commit ground truth for run %s: %s", run_id, e)
        raise HTTPException(500, f"Failed to push ground truth: {e}")

    # Trigger the GitHub Actions workflow
    try:
        trigger.trigger_workflow(
            branch=branch,
            cycles=cycles,
            experiments=experiments,
            model=model,
            org_id=ctx.org_id,
            project_id=project.id,
            run_id=run_id,
        )
    except trigger.WiggumTriggerError as e:
        db.update_wiggum_run(run_id, status="failed")
        logger.error("Failed to trigger workflow for run %s: %s", run_id, e)
        raise HTTPException(500, f"Failed to trigger workflow: {e}")

    db.update_wiggum_run(run_id, status="queued")

    return {
        "run_id": run.id,
        "status": "queued",
        "branch": branch,
    }


@router.get("/status")
async def get_wiggum_status(
    project_id: str = "",
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Get latest Wiggum run status for current org+project."""
    ctx = await get_org_context(authorization, x_org_id)

    # Accept project_id from query param OR header
    pid = project_id or x_project_id
    project = _resolve_project(ctx, pid) if pid else None
    resolved_pid = project.id if project else pid or ""
    latest = db.get_latest_wiggum_run(ctx.org_id, resolved_pid)

    if not latest:
        return {"status": "none", "message": "No Wiggum runs found for this project"}

    # If the run is active and we have a github_run_id, poll GitHub for updated status
    if latest.status in ACTIVE_STATUSES and latest.github_run_id:
        try:
            gh_status = trigger.get_workflow_run_status(latest.github_run_id)
            updated_status = _map_github_status(gh_status)

            updates: dict = {"status": updated_status}
            if updated_status not in ACTIVE_STATUSES:
                updates["completed_at"] = datetime.now(timezone.utc).isoformat()

            db.update_wiggum_run(latest.id, **updates)

            return {
                **latest.to_dict(),
                "status": updated_status,
                "github_status": gh_status,
            }
        except trigger.WiggumTriggerError:
            # If we can't reach GitHub, return the last known state
            pass

    # If active but no github_run_id yet, try to find it
    if latest.status in ACTIVE_STATUSES and not latest.github_run_id:
        try:
            github_run_id = trigger.find_triggered_run(
                latest.branch, latest.id, latest.started_at,
            )
            if github_run_id:
                db.update_wiggum_run(latest.id, github_run_id=github_run_id)
                return {**latest.to_dict(), "github_run_id": github_run_id}
        except trigger.WiggumTriggerError:
            pass

    return latest.to_dict()


@router.get("/history")
async def get_wiggum_history(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """List all Wiggum runs for current org+project."""
    ctx = await get_org_context(authorization, x_org_id)

    project = _resolve_project(ctx, x_project_id)
    project_id = project.id if project else x_project_id or ""
    runs = db.list_wiggum_runs(ctx.org_id, project_id)

    return runs


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

def _map_github_status(gh_status: dict) -> str:
    """Map GitHub Actions status/conclusion to our internal status."""
    status = gh_status.get("status", "")
    conclusion = gh_status.get("conclusion")

    if status == "completed":
        if conclusion == "success":
            return "completed"
        return "failed"

    if status in ("queued", "waiting", "pending"):
        return "queued"

    if status == "in_progress":
        return "in_progress"

    return status or "unknown"
