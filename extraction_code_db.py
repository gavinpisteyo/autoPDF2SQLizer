"""CRUD for project extraction code stored in the database."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from metadata import _get_conn


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ExtractionCode:
    project_id: str
    prompt: str
    processing_code: str
    accuracy: float
    version: int
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtractionVersion:
    id: str
    project_id: str
    prompt: str
    processing_code: str
    accuracy: float
    version: int
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Current extraction code (one per project)
# ---------------------------------------------------------------------------

def get_extraction_code(project_id: str) -> ExtractionCode | None:
    """Get the current extraction code for a project."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM project_extraction_code WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return ExtractionCode(**dict(row))


def save_extraction_code(
    project_id: str, prompt: str, code: str, accuracy: float, version: int,
) -> ExtractionCode:
    """Upsert the current extraction code for a project."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()

    existing = conn.execute(
        "SELECT 1 FROM project_extraction_code WHERE project_id = ?",
        (project_id,),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE project_extraction_code "
            "SET prompt = ?, processing_code = ?, accuracy = ?, version = ?, updated_at = ? "
            "WHERE project_id = ?",
            (prompt, code, accuracy, version, now, project_id),
        )
    else:
        conn.execute(
            "INSERT INTO project_extraction_code "
            "(project_id, prompt, processing_code, accuracy, version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, prompt, code, accuracy, version, now, now),
        )

    conn.commit()
    conn.close()

    return ExtractionCode(
        project_id=project_id,
        prompt=prompt,
        processing_code=code,
        accuracy=accuracy,
        version=version,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------

def save_extraction_version(
    project_id: str, prompt: str, code: str, accuracy: float, version: int,
) -> str:
    """Save a snapshot of extraction code as a version. Returns the version id."""
    conn = _get_conn()
    version_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO project_extraction_versions "
        "(id, project_id, prompt, processing_code, accuracy, version, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (version_id, project_id, prompt, code, accuracy, version, now),
    )
    conn.commit()
    conn.close()

    return version_id


def get_extraction_versions(project_id: str) -> list[ExtractionVersion]:
    """List all extraction code versions for a project, newest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM project_extraction_versions "
        "WHERE project_id = ? ORDER BY version DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    return [ExtractionVersion(**dict(r)) for r in rows]


def get_best_version(project_id: str) -> ExtractionVersion | None:
    """Get the version with the highest accuracy for a project."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM project_extraction_versions "
        "WHERE project_id = ? ORDER BY accuracy DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return ExtractionVersion(**dict(row))
