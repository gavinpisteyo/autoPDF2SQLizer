"""
Wiggum Routes -- FastAPI endpoints for triggering and monitoring Wiggum optimization runs.

The loop now runs server-side (wiggum_loop.py) in a background thread.
The frontend polls /api/wiggum/status which reads directly from the DB.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, Header, HTTPException

from auth import OrgContext, OrgRole, get_org_context
from auth.dependencies import DATA_DIR
from auth.models import role_at_least
import metadata as db

logger = logging.getLogger("autopdf2sqlizer.wiggum_routes")

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
    """Generate a branch-style label from org name + project slug."""
    clean_org = re.sub(r"[^\w\-]", "-", org_name.lower().strip())
    return f"clients/{clean_org}-{project_slug}"


def _has_ground_truth(org_id: str, project_slug: str) -> bool:
    """Check that ground truth JSON files exist in the project data directory."""
    gt_path = DATA_DIR / org_id / project_slug / "ground_truth"
    if not gt_path.exists():
        return False
    # At least one ground truth JSON must exist
    return any(gt_path.rglob("*.json"))


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
    """Start a Wiggum optimization run (server-side loop)."""
    from wiggum_loop import run_loop

    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.DEVELOPER):
        raise HTTPException(403, f"Requires {OrgRole.DEVELOPER.value}, you have {ctx.role.value}")

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
    if not _has_ground_truth(ctx.org_id, project.slug):
        raise HTTPException(
            400,
            "No ground truth data found. Upload and correct documents before starting Wiggum.",
        )

    # Resolve org name for branch naming
    org = db.get_org(ctx.org_id)
    org_name = org.name if org else ctx.org_id

    # Generate branch label and run ID
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

    # Fire-and-forget: launch the blocking loop in a background thread.
    # Deliberately NOT awaited -- the frontend polls /api/wiggum/status.
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        None,
        lambda: run_loop(
            ctx.org_id, project.id, run_id,
            max_iterations=cycles * experiments,
            model=model,
        ),
    )

    return {
        "run_id": run.id,
        "status": "pending",
        "branch": branch,
    }


@router.get("/status")
async def get_wiggum_status(
    project_id: str = "",
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Get latest Wiggum run status for current org+project.

    The server-side loop updates the DB directly as it runs,
    so this endpoint simply reads the latest state.
    """
    ctx = await get_org_context(authorization, x_org_id)

    # Accept project_id from query param OR header
    pid = project_id or x_project_id
    project = _resolve_project(ctx, pid) if pid else None
    resolved_pid = project.id if project else pid or ""
    latest = db.get_latest_wiggum_run(ctx.org_id, resolved_pid)

    if not latest:
        return {"status": "none", "message": "No Wiggum runs found for this project"}

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
