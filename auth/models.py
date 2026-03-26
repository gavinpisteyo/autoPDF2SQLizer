"""Auth data models — immutable, used throughout the app via Depends()."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel


class OrgRole(str, Enum):
    ORG_ADMIN = "org_admin"
    DEVELOPER = "developer"
    BUSINESS_USER = "business_user"
    VIEWER = "viewer"


# Ordered from most to least privileged — used for "at least this role" checks
ROLE_HIERARCHY = [OrgRole.ORG_ADMIN, OrgRole.DEVELOPER, OrgRole.BUSINESS_USER, OrgRole.VIEWER]

# Map Auth0 permissions → role (first match wins, check most privileged first)
PERMISSION_ROLE_MAP: dict[str, OrgRole] = {
    "org:admin": OrgRole.ORG_ADMIN,
    "evaluate:run": OrgRole.DEVELOPER,
    "extract:run": OrgRole.BUSINESS_USER,
    "schemas:read": OrgRole.VIEWER,
}


class AuthUser(BaseModel):
    """Decoded JWT claims for the authenticated user."""
    model_config = {"frozen": True}

    sub: str
    email: str = ""
    name: str = ""
    org_id: str | None = None
    permissions: list[str] = []
    raw_token: str = ""


class OrgContext(BaseModel):
    """Resolved org + role context for the current request."""
    model_config = {"frozen": True}

    org_id: str
    user: AuthUser
    role: OrgRole


class OrgPaths(BaseModel):
    """Org-scoped directory paths for data isolation."""
    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    schemas: Path
    custom_schemas: Path
    ground_truth: Path
    uploads: Path
    cache: Path
    results: Path

    def ensure_dirs(self) -> None:
        """Create all directories if they don't exist."""
        for field in self.model_fields:
            path = getattr(self, field)
            path.mkdir(parents=True, exist_ok=True)


def resolve_role(permissions: list[str]) -> OrgRole:
    """Determine the user's role from their Auth0 permissions."""
    perm_set = set(permissions)
    for perm, role in PERMISSION_ROLE_MAP.items():
        if perm in perm_set:
            return role
    return OrgRole.VIEWER


def role_at_least(role: OrgRole, minimum: OrgRole) -> bool:
    """Check if a role meets or exceeds the minimum required level."""
    return ROLE_HIERARCHY.index(role) <= ROLE_HIERARCHY.index(minimum)
