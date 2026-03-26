"""
Metadata database — projects, project membership, and org join requests.
Lightweight SQLite store for application-level data that Auth0 doesn't handle.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "metadata.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            name TEXT NOT NULL,
            slug TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(org_id, slug)
        );

        CREATE TABLE IF NOT EXISTS project_members (
            project_id TEXT NOT NULL,
            user_sub TEXT NOT NULL,
            user_email TEXT DEFAULT '',
            added_by TEXT DEFAULT '',
            added_at TEXT NOT NULL,
            PRIMARY KEY (project_id, user_sub),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS join_requests (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            user_sub TEXT NOT NULL,
            user_email TEXT DEFAULT '',
            user_name TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            requested_at TEXT NOT NULL,
            resolved_by TEXT DEFAULT '',
            resolved_at TEXT DEFAULT ''
        );
    """)
    conn.commit()
    conn.close()


# Auto-init on import
init_db()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Project:
    id: str
    org_id: str
    name: str
    slug: str
    description: str
    created_by: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProjectMember:
    project_id: str
    user_sub: str
    user_email: str
    added_by: str
    added_at: str


@dataclass
class JoinRequest:
    id: str
    org_id: str
    user_sub: str
    user_email: str
    user_name: str
    status: str
    requested_at: str
    resolved_by: str
    resolved_at: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def create_project(org_id: str, name: str, slug: str, description: str, created_by: str) -> Project:
    conn = _get_conn()
    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO projects (id, org_id, name, slug, description, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, org_id, name, slug, description, created_by, now),
    )
    # Auto-add creator as member
    conn.execute(
        "INSERT INTO project_members (project_id, user_sub, user_email, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, created_by, "", "system", now),
    )
    conn.commit()
    conn.close()

    return Project(id=project_id, org_id=org_id, name=name, slug=slug,
                   description=description, created_by=created_by, created_at=now)


def list_projects(org_id: str, user_sub: str, is_admin: bool) -> list[dict]:
    """List projects. Admins see all org projects; others see only their assigned projects."""
    conn = _get_conn()

    if is_admin:
        rows = conn.execute(
            "SELECT * FROM projects WHERE org_id = ? ORDER BY created_at",
            (org_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT p.* FROM projects p
               JOIN project_members pm ON p.id = pm.project_id
               WHERE p.org_id = ? AND pm.user_sub = ?
               ORDER BY p.created_at""",
            (org_id, user_sub),
        ).fetchall()

    projects = []
    for row in rows:
        p = dict(row)
        # Add member count
        count = conn.execute(
            "SELECT COUNT(*) as c FROM project_members WHERE project_id = ?",
            (p["id"],),
        ).fetchone()["c"]
        p["member_count"] = count
        projects.append(p)

    conn.close()
    return projects


def get_project(project_id: str) -> Project | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return Project(**dict(row))


def get_project_by_slug(org_id: str, slug: str) -> Project | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM projects WHERE org_id = ? AND slug = ?",
        (org_id, slug),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return Project(**dict(row))


def is_project_member(project_id: str, user_sub: str) -> bool:
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM project_members WHERE project_id = ? AND user_sub = ?",
        (project_id, user_sub),
    ).fetchone()
    conn.close()
    return row is not None


# ---------------------------------------------------------------------------
# Project members
# ---------------------------------------------------------------------------

def add_project_member(project_id: str, user_sub: str, user_email: str, added_by: str):
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO project_members (project_id, user_sub, user_email, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, user_sub, user_email, added_by, now),
    )
    conn.commit()
    conn.close()


def remove_project_member(project_id: str, user_sub: str):
    conn = _get_conn()
    conn.execute(
        "DELETE FROM project_members WHERE project_id = ? AND user_sub = ?",
        (project_id, user_sub),
    )
    conn.commit()
    conn.close()


def list_project_members(project_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM project_members WHERE project_id = ? ORDER BY added_at",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Join requests
# ---------------------------------------------------------------------------

def create_join_request(org_id: str, user_sub: str, user_email: str, user_name: str) -> JoinRequest:
    conn = _get_conn()

    # Check for existing pending request
    existing = conn.execute(
        "SELECT id FROM join_requests WHERE org_id = ? AND user_sub = ? AND status = 'pending'",
        (org_id, user_sub),
    ).fetchone()
    if existing:
        conn.close()
        raise ValueError("You already have a pending request for this organization")

    req_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO join_requests (id, org_id, user_sub, user_email, user_name, status, requested_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (req_id, org_id, user_sub, user_email, user_name, now),
    )
    conn.commit()
    conn.close()

    return JoinRequest(id=req_id, org_id=org_id, user_sub=user_sub, user_email=user_email,
                       user_name=user_name, status="pending", requested_at=now,
                       resolved_by="", resolved_at="")


def list_join_requests(org_id: str, status: str = "pending") -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM join_requests WHERE org_id = ? AND status = ? ORDER BY requested_at DESC",
        (org_id, status),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_join_request(request_id: str, resolved_by: str, approve: bool) -> JoinRequest | None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    status = "approved" if approve else "rejected"

    conn.execute(
        "UPDATE join_requests SET status = ?, resolved_by = ?, resolved_at = ? WHERE id = ? AND status = 'pending'",
        (status, resolved_by, now, request_id),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM join_requests WHERE id = ?", (request_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return JoinRequest(**dict(row))
