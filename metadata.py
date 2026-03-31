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

def _resolve_db_path() -> Path:
    """Use persistent storage on Azure App Service, local file otherwise."""
    azure_site = Path("/home/site")
    if azure_site.exists():
        data_dir = Path("/home/data")
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "metadata.db"
    return Path(__file__).parent / "metadata.db"

DB_PATH = _resolve_db_path()


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

        CREATE TABLE IF NOT EXISTS org_members (
            org_id TEXT NOT NULL,
            user_sub TEXT NOT NULL,
            user_email TEXT DEFAULT '',
            user_name TEXT DEFAULT '',
            role TEXT DEFAULT 'viewer',
            joined_at TEXT NOT NULL,
            PRIMARY KEY (org_id, user_sub)
        );

        CREATE TABLE IF NOT EXISTS orgs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
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

        CREATE TABLE IF NOT EXISTS wiggum_runs (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            branch TEXT NOT NULL,
            github_run_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            cycles INTEGER DEFAULT 5,
            experiments INTEGER DEFAULT 5,
            model TEXT DEFAULT 'claude-sonnet-4-20250514',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            best_accuracy REAL,
            accuracy_history TEXT,
            FOREIGN KEY (org_id) REFERENCES orgs(id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS org_databases (
            org_id TEXT PRIMARY KEY,
            database_name TEXT NOT NULL,
            server TEXT NOT NULL,
            username TEXT NOT NULL,
            password_encrypted TEXT NOT NULL,
            port INTEGER DEFAULT 1433,
            status TEXT DEFAULT 'provisioning',
            created_at TEXT NOT NULL,
            ready_at TEXT,
            error TEXT,
            FOREIGN KEY (org_id) REFERENCES orgs(id)
        );

        CREATE TABLE IF NOT EXISTS project_extraction_code (
            project_id TEXT PRIMARY KEY,
            prompt TEXT NOT NULL DEFAULT '',
            processing_code TEXT NOT NULL DEFAULT '',
            accuracy REAL DEFAULT 0.0,
            version INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS project_extraction_versions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            prompt TEXT NOT NULL DEFAULT '',
            processing_code TEXT NOT NULL DEFAULT '',
            accuracy REAL DEFAULT 0.0,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
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
class OrgDatabase:
    org_id: str
    database_name: str
    server: str
    username: str
    password_encrypted: str
    port: int
    status: str
    created_at: str
    ready_at: str | None
    error: str | None

    def to_dict(self) -> dict:
        """Return a safe dict — never includes password."""
        d = asdict(self)
        d.pop("password_encrypted", None)
        return d


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


def delete_project(project_id: str) -> None:
    """Delete a project and all its members."""
    conn = _get_conn()
    conn.execute("DELETE FROM project_members WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()


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


# ---------------------------------------------------------------------------
# Organizations (app-managed, independent of Auth0 orgs)
# ---------------------------------------------------------------------------

@dataclass
class Org:
    id: str
    name: str
    created_by: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def create_org(name: str, creator_sub: str, creator_email: str = "", creator_name: str = "") -> Org:
    """Create an org and make the creator an admin."""
    conn = _get_conn()
    org_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO orgs (id, name, created_by, created_at) VALUES (?, ?, ?, ?)",
        (org_id, name, creator_sub, now),
    )
    conn.execute(
        "INSERT INTO org_members (org_id, user_sub, user_email, user_name, role, joined_at) VALUES (?, ?, ?, ?, 'org_admin', ?)",
        (org_id, creator_sub, creator_email, creator_name, now),
    )
    conn.commit()
    conn.close()

    return Org(id=org_id, name=name, created_by=creator_sub, created_at=now)


def list_user_orgs(user_sub: str) -> list[dict]:
    """List all orgs a user belongs to, with their role in each."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT o.id, o.name, o.created_at, om.role
           FROM orgs o
           JOIN org_members om ON o.id = om.org_id
           WHERE om.user_sub = ?
           ORDER BY o.created_at""",
        (user_sub,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_org(org_id: str) -> Org | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM orgs WHERE id = ?", (org_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return Org(**dict(row))


def get_user_org_role(org_id: str, user_sub: str) -> str | None:
    """Get a user's role in an org from the local DB. Returns None if not a member."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT role FROM org_members WHERE org_id = ? AND user_sub = ?",
        (org_id, user_sub),
    ).fetchone()
    conn.close()
    return row["role"] if row else None


def add_org_member(org_id: str, user_sub: str, role: str = "viewer",
                   user_email: str = "", user_name: str = ""):
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO org_members (org_id, user_sub, user_email, user_name, role, joined_at) VALUES (?, ?, ?, ?, ?, ?)",
        (org_id, user_sub, user_email, user_name, role, now),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Org Databases (per-customer Azure SQL)
# ---------------------------------------------------------------------------

def create_org_database(
    org_id: str,
    database_name: str,
    server: str,
    username: str,
    password: str,
    port: int = 1433,
) -> OrgDatabase:
    """Create an org_databases record for a newly provisioned database."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO org_databases "
        "(org_id, database_name, server, username, password_encrypted, port, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'provisioning', ?)",
        (org_id, database_name, server, username, password, port, now),
    )
    conn.commit()
    conn.close()

    return OrgDatabase(
        org_id=org_id,
        database_name=database_name,
        server=server,
        username=username,
        password_encrypted=password,
        port=port,
        status="provisioning",
        created_at=now,
        ready_at=None,
        error=None,
    )


def get_org_database(org_id: str) -> OrgDatabase | None:
    """Get the database record for an org."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM org_databases WHERE org_id = ?", (org_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return OrgDatabase(**dict(row))


def update_org_database_status(
    org_id: str,
    status: str,
    error: str | None = None,
    ready_at: str | None = None,
) -> None:
    """Update the provisioning status of an org's database."""
    conn = _get_conn()
    conn.execute(
        "UPDATE org_databases SET status = ?, error = ?, ready_at = ? WHERE org_id = ?",
        (status, error, ready_at, org_id),
    )
    conn.commit()
    conn.close()


def update_org_database_credentials(
    org_id: str,
    database_name: str,
    server: str,
    username: str,
    password: str,
    port: int,
) -> None:
    """Update the actual connection details after provisioning completes."""
    conn = _get_conn()
    conn.execute(
        "UPDATE org_databases "
        "SET database_name = ?, server = ?, username = ?, password_encrypted = ?, port = ? "
        "WHERE org_id = ?",
        (database_name, server, username, password, port, org_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Wiggum runs
# ---------------------------------------------------------------------------

@dataclass
class WiggumRun:
    id: str
    org_id: str
    project_id: str
    branch: str
    github_run_id: int | None
    status: str
    cycles: int
    experiments: int
    model: str
    started_at: str
    completed_at: str | None
    best_accuracy: float | None
    accuracy_history: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def create_wiggum_run(
    id: str,
    org_id: str,
    project_id: str,
    branch: str,
    cycles: int,
    experiments: int,
    model: str,
) -> WiggumRun:
    """Create a new Wiggum run record."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO wiggum_runs (id, org_id, project_id, branch, status, cycles, experiments, model, started_at) "
        "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
        (id, org_id, project_id, branch, cycles, experiments, model, now),
    )
    conn.commit()
    conn.close()

    return WiggumRun(
        id=id, org_id=org_id, project_id=project_id, branch=branch,
        github_run_id=None, status="pending", cycles=cycles,
        experiments=experiments, model=model, started_at=now,
        completed_at=None, best_accuracy=None, accuracy_history=None,
    )


def update_wiggum_run(id: str, **kwargs) -> None:
    """Update fields on a Wiggum run. Only specified kwargs are updated."""
    if not kwargs:
        return

    allowed = {
        "github_run_id", "status", "completed_at",
        "best_accuracy", "accuracy_history",
    }
    invalid = set(kwargs.keys()) - allowed
    if invalid:
        raise ValueError(f"Cannot update fields: {invalid}")

    conn = _get_conn()
    set_clauses = ", ".join(f'"{k}" = ?' for k in kwargs)
    values = list(kwargs.values()) + [id]

    conn.execute(
        f"UPDATE wiggum_runs SET {set_clauses} WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()


def get_wiggum_run(id: str) -> WiggumRun | None:
    """Get a single Wiggum run by ID."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM wiggum_runs WHERE id = ?", (id,)).fetchone()
    conn.close()
    if not row:
        return None
    return WiggumRun(**dict(row))


def get_latest_wiggum_run(org_id: str, project_id: str) -> WiggumRun | None:
    """Get the most recent Wiggum run for an org+project."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM wiggum_runs WHERE org_id = ? AND project_id = ? ORDER BY started_at DESC LIMIT 1",
        (org_id, project_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return WiggumRun(**dict(row))


def list_wiggum_runs(org_id: str, project_id: str) -> list[dict]:
    """List all Wiggum runs for an org+project, newest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM wiggum_runs WHERE org_id = ? AND project_id = ? ORDER BY started_at DESC",
        (org_id, project_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
