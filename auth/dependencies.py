"""
FastAPI dependency functions for authentication and authorization.
Injected via Depends() — keeps auth logic out of route handlers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from .config import get_auth_config
from .models import (
    AuthUser,
    OrgContext,
    OrgPaths,
    OrgRole,
    resolve_role,
    role_at_least,
)

# Cache the JWKS client (fetches and caches Auth0's public signing keys)
_jwks_client: PyJWKClient | None = None

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

# Global fallback dirs (used when auth is disabled)
GLOBAL_SCHEMAS_DIR = BASE_DIR / "schemas"
GLOBAL_CUSTOM_SCHEMAS_DIR = GLOBAL_SCHEMAS_DIR / "custom"
GLOBAL_GROUND_TRUTH_DIR = BASE_DIR / "ground_truth"
GLOBAL_UPLOADS_DIR = BASE_DIR / "uploads"
GLOBAL_CACHE_DIR = BASE_DIR / "cache"
GLOBAL_RESULTS_DIR = BASE_DIR / "results"

# Mock user for dev mode (all permissions)
_MOCK_USER = AuthUser(
    sub="dev|local",
    email="dev@localhost",
    name="Dev User",
    org_id="default",
    permissions=["org:admin", "schemas:read", "schemas:write", "extract:run",
                 "extract:read", "ground_truth:read", "ground_truth:write",
                 "evaluate:run", "evaluate:read", "database:connect",
                 "database:execute"],
)


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        config = get_auth_config()
        _jwks_client = PyJWKClient(config.jwks_uri, cache_jwk_set=True, lifespan=43200)
    return _jwks_client


# ---------------------------------------------------------------------------
# Core dependencies
# ---------------------------------------------------------------------------

async def get_current_user(authorization: str = Header(default="")) -> AuthUser:
    """
    Validate the JWT from the Authorization header and return the user.
    When AUTH_ENABLED=false, returns a mock admin user.
    """
    config = get_auth_config()

    if not config.auth_enabled:
        return _MOCK_USER

    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=config.auth0_algorithms,
            audience=config.auth0_api_audience,
            issuer=config.issuer,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token has expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(401, f"Invalid token: {e}")

    return AuthUser(
        sub=payload.get("sub", ""),
        email=payload.get("email", payload.get("https://autopdf2sqlizer.com/email", "")),
        name=payload.get("name", payload.get("https://autopdf2sqlizer.com/name", "")),
        org_id=payload.get("org_id"),
        permissions=payload.get("permissions", []),
        raw_token=token,
    )


async def get_org_context(
    user: AuthUser = None,
    x_org_id: str = Header(default=""),
) -> OrgContext:
    """
    Resolve the active organization and the user's role within it.
    Org comes from the token's org_id claim, or the X-Org-Id header.
    """
    # In practice, `user` is injected by FastAPI's Depends system.
    # This signature is for documentation; actual wiring is in the route.
    if user is None:
        user = await get_current_user()

    config = get_auth_config()

    if not config.auth_enabled:
        return OrgContext(org_id="default", user=user, role=OrgRole.ORG_ADMIN)

    org_id = user.org_id or x_org_id
    if not org_id:
        raise HTTPException(400, "No organization context. Include org_id in token or X-Org-Id header.")

    role = resolve_role(user.permissions)

    return OrgContext(org_id=org_id, user=user, role=role)


async def resolve_org_paths(
    ctx: OrgContext = None,
) -> OrgPaths:
    """
    Build org-scoped directory paths.
    When auth is disabled, returns the original flat global paths.
    """
    if ctx is None:
        ctx = await get_org_context()

    config = get_auth_config()

    if not config.auth_enabled:
        paths = OrgPaths(
            schemas=GLOBAL_SCHEMAS_DIR,
            custom_schemas=GLOBAL_CUSTOM_SCHEMAS_DIR,
            ground_truth=GLOBAL_GROUND_TRUTH_DIR,
            uploads=GLOBAL_UPLOADS_DIR,
            cache=GLOBAL_CACHE_DIR,
            results=GLOBAL_RESULTS_DIR,
        )
    else:
        org_dir = DATA_DIR / ctx.org_id
        paths = OrgPaths(
            schemas=GLOBAL_SCHEMAS_DIR,  # built-in schemas are always global
            custom_schemas=org_dir / "schemas" / "custom",
            ground_truth=org_dir / "ground_truth",
            uploads=org_dir / "uploads",
            cache=org_dir / "cache",
            results=org_dir / "results",
        )

    paths.ensure_dirs()
    return paths


# ---------------------------------------------------------------------------
# Role-checking dependency factory
# ---------------------------------------------------------------------------

def require_role(*allowed_roles: OrgRole) -> Callable:
    """
    Dependency factory: returns a dependency that checks the user's role.

    Usage:
        @app.post("/api/evaluate")
        async def run_eval(ctx: OrgContext = Depends(require_role(OrgRole.DEVELOPER, OrgRole.ORG_ADMIN))):
            ...
    """
    async def _checker(
        authorization: str = Header(default=""),
        x_org_id: str = Header(default=""),
    ) -> OrgContext:
        user = await get_current_user(authorization)
        ctx = await get_org_context(user, x_org_id)

        if ctx.role not in allowed_roles:
            raise HTTPException(
                403,
                f"Insufficient permissions. Required: {[r.value for r in allowed_roles]}, "
                f"your role: {ctx.role.value}",
            )
        return ctx

    return _checker


def require_at_least(minimum_role: OrgRole) -> Callable:
    """
    Dependency factory: checks the user meets a minimum role level.

    Usage:
        @app.post("/api/extract")
        async def extract(ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER))):
            ...
    """
    async def _checker(
        authorization: str = Header(default=""),
        x_org_id: str = Header(default=""),
    ) -> OrgContext:
        user = await get_current_user(authorization)
        ctx = await get_org_context(user, x_org_id)

        if not role_at_least(ctx.role, minimum_role):
            raise HTTPException(
                403,
                f"Insufficient permissions. Minimum required: {minimum_role.value}, "
                f"your role: {ctx.role.value}",
            )
        return ctx

    return _checker
