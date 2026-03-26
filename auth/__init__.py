"""
Auth module — Auth0 multi-tenant authentication and authorization.
Keeps auth concerns separate from business logic.
"""

from .config import AuthConfig, get_auth_config
from .dependencies import (
    get_current_user,
    get_org_context,
    require_at_least,
    require_role,
    resolve_org_paths,
)
from .models import AuthUser, OrgContext, OrgPaths, OrgRole, role_at_least

__all__ = [
    "AuthConfig",
    "AuthUser",
    "OrgContext",
    "OrgPaths",
    "OrgRole",
    "get_auth_config",
    "get_current_user",
    "get_org_context",
    "require_at_least",
    "require_role",
    "resolve_org_paths",
    "role_at_least",
]
