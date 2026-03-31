"""
autoPDF2SQLizer — FastAPI web application.
Upload PDFs, select document types, define schemas, manage ground truth,
and run extraction + evaluation.

Usage:
    uv run uvicorn app:app --reload --port 8000
"""

import json
import logging
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
# BaseHTTPMiddleware removed — it breaks file uploads by consuming the request body

from auth import (
    OrgContext,
    OrgPaths,
    OrgRole,
    get_org_context,
    resolve_org_paths,
)
from auth.models import role_at_least
from doc_intel import analyze_document, cache_result, get_cached_result
from process import extract
from sql_gen import generate_create_table, json_to_sql
from wiggum_routes import router as wiggum_router

llm = Anthropic()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("autopdf2sqlizer")

# ---------------------------------------------------------------------------
# Paths (global — built-in schemas only; org data uses OrgPaths)
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
SCHEMAS_DIR = BASE_DIR / "schemas"
GLOBAL_SCHEMAS_DIR = SCHEMAS_DIR  # alias used in some endpoints


# ---------------------------------------------------------------------------
# Auth helper — replaces all Depends(require_at_least / resolve_org_paths)
# ---------------------------------------------------------------------------

async def _get_auth(
    authorization: str,
    x_org_id: str,
    x_project_id: str = "",
    min_role: OrgRole = OrgRole.VIEWER,
) -> tuple[OrgContext, OrgPaths]:
    """Simple auth + paths helper. No Depends() magic."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, min_role):
        raise HTTPException(403, f"Requires {min_role.value}, you have {ctx.role.value}")
    paths = await resolve_org_paths(authorization, x_org_id, x_project_id)
    return ctx, paths


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="autoPDF2SQLizer", version="0.1.0")

# NOTE: CORS middleware is added AFTER RequestLoggingMiddleware below
# so that CORS runs first (Starlette processes last-added middleware first)


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

# CORS middleware (no BaseHTTPMiddleware — it breaks file uploads)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
        "https://autopdf2sqlizer.azurewebsites.net",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve React build if available, fall back to legacy static/
STATIC_BUILD_DIR = BASE_DIR / "static-build"
LEGACY_STATIC_DIR = BASE_DIR / "static"

if STATIC_BUILD_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_BUILD_DIR / "assets")), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_BUILD_DIR / "index.html"))
else:
    app.mount("/static", StaticFiles(directory=str(LEGACY_STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(str(LEGACY_STATIC_DIR / "index.html"))


app.include_router(wiggum_router)


@app.get("/api/health")
async def health():
    """Health check — verifies API keys and services."""
    checks = {}
    checks["anthropic_key_set"] = bool(os.getenv("ANTHROPIC_API_KEY"))
    checks["azure_di_key_set"] = bool(os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY"))
    checks["db_path"] = str(db.DB_PATH)
    checks["db_exists"] = db.DB_PATH.exists()
    # Quick Anthropic API test
    try:
        resp = llm.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say ok"}],
        )
        checks["anthropic_api"] = "ok"
    except Exception as e:
        checks["anthropic_api"] = f"error: {e}"
    return checks


# ---------------------------------------------------------------------------
# Organizations & Projects
# ---------------------------------------------------------------------------

import re as _re
import metadata as db
from auth import get_current_user
from auth.models import AuthUser


@app.get("/api/me")
async def get_me(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Get current user info + resolved role for active org."""
    user = await get_current_user(authorization)
    role = "viewer"
    org_id = user.org_id or x_org_id
    if org_id:
        # Check local DB for role
        local_role = db.get_user_org_role(org_id, user.sub)
        if local_role:
            role = local_role
        # Auth0 permissions override if present
        from auth.models import resolve_role as _resolve, OrgRole
        token_role = _resolve(user.permissions)
        if token_role != OrgRole.VIEWER:
            role = token_role.value
    return {
        "sub": user.sub,
        "email": user.email,
        "name": user.name,
        "org_id": org_id,
        "role": role,
    }


@app.post("/api/orgs")
async def create_org(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    authorization: str = Header(default=""),
):
    """Create a new organization. The creator becomes admin."""
    from db_provisioner import is_azure_sql_configured, provision_database

    user = await get_current_user(authorization)
    org = db.create_org(name, user.sub, user.email, user.name)

    result = org.to_dict()
    if is_azure_sql_configured():
        # Create a placeholder record and provision in the background
        db.create_org_database(
            org_id=org.id,
            database_name="pending",
            server=os.getenv("AZURE_SQL_SERVER", ""),
            username="pending",
            password="pending",
            port=int(os.getenv("AZURE_SQL_PORT", "1433")),
        )
        background_tasks.add_task(_provision_org_db, org.id)
        result["db_status"] = "provisioning"
    else:
        result["db_status"] = "sqlite"

    return result


def _provision_org_db(org_id: str) -> None:
    """Background task: provision an Azure SQL Database for an org."""
    from db_provisioner import provision_database
    try:
        provision_database(org_id)
    except Exception as exc:
        logger.error("Background DB provisioning failed for org %s: %s", org_id, exc)


@app.get("/api/me/orgs")
async def list_my_orgs(
    authorization: str = Header(default=""),
):
    """List all orgs the current user belongs to."""
    user = await get_current_user(authorization)
    return db.list_user_orgs(user.sub)


@app.post("/api/orgs/join")
async def request_join_org(
    org_id: str = Form(...),
    authorization: str = Header(default=""),
):
    """Request to join an organization. Admin must approve."""
    user = await get_current_user(authorization)
    try:
        req = db.create_join_request(org_id, user.sub, user.email, user.name)
        return req.to_dict()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/orgs/requests")
async def list_join_requests(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """List pending join requests for the current org. Admin only."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.ORG_ADMIN):
        raise HTTPException(403, f"Requires {OrgRole.ORG_ADMIN.value}, you have {ctx.role.value}")
    return db.list_join_requests(ctx.org_id, status="pending")


@app.post("/api/orgs/requests/{request_id}/resolve")
async def resolve_join_request(
    request_id: str,
    approve: bool = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Approve or reject a join request. Admin only."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.ORG_ADMIN):
        raise HTTPException(403, f"Requires {OrgRole.ORG_ADMIN.value}, you have {ctx.role.value}")
    result = db.resolve_join_request(request_id, ctx.user.sub, approve)
    if not result:
        raise HTTPException(404, "Request not found")
    # If approved, add them to the org as a business_user
    if approve and result.status == "approved":
        db.add_org_member(ctx.org_id, result.user_sub, "business_user",
                          result.user_email, result.user_name)
    return result.to_dict()


@app.get("/api/projects")
async def list_projects(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """List projects in the current org. Admins see all; others see assigned only."""
    ctx = await get_org_context(authorization, x_org_id)
    is_admin = ctx.role == OrgRole.ORG_ADMIN
    return db.list_projects(ctx.org_id, ctx.user.sub, is_admin)


@app.post("/api/projects")
async def create_project(
    name: str = Form(...),
    slug: str = Form(...),
    description: str = Form(""),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Create a new project in the current org. Admin only."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.ORG_ADMIN):
        raise HTTPException(403, f"Requires org_admin, you have {ctx.role.value}")
    clean_slug = _re.sub(r"[^\w\-]", "-", slug.lower().strip())
    if not clean_slug:
        raise HTTPException(400, "Invalid slug")

    existing = db.get_project_by_slug(ctx.org_id, clean_slug)
    if existing:
        raise HTTPException(409, f"Project with slug '{clean_slug}' already exists")

    project = db.create_project(ctx.org_id, name, clean_slug, description, ctx.user.sub)
    return project.to_dict()


@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: str,
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Get project details + members."""
    ctx = await get_org_context(authorization, x_org_id)
    project = db.get_project(project_id)
    if not project or project.org_id != ctx.org_id:
        raise HTTPException(404, "Project not found")
    if ctx.role != OrgRole.ORG_ADMIN and not db.is_project_member(project_id, ctx.user.sub):
        raise HTTPException(403, "Not a member of this project")

    members = db.list_project_members(project_id)
    return {**project.to_dict(), "members": members}


@app.post("/api/projects/{project_id}/members")
async def add_project_member(
    project_id: str,
    user_sub: str = Form(...),
    user_email: str = Form(""),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Add a member to a project. Admin only."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.ORG_ADMIN):
        raise HTTPException(403, f"Requires {OrgRole.ORG_ADMIN.value}, you have {ctx.role.value}")
    project = db.get_project(project_id)
    if not project or project.org_id != ctx.org_id:
        raise HTTPException(404, "Project not found")

    db.add_project_member(project_id, user_sub, user_email, ctx.user.sub)
    return {"status": "added", "project_id": project_id, "user_sub": user_sub}


@app.delete("/api/projects/{project_id}/members/{user_sub}")
async def remove_project_member(
    project_id: str,
    user_sub: str,
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Remove a member from a project. Admin only."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.ORG_ADMIN):
        raise HTTPException(403, f"Requires {OrgRole.ORG_ADMIN.value}, you have {ctx.role.value}")
    db.remove_project_member(project_id, user_sub)
    return {"status": "removed"}


@app.post("/api/projects/{project_id}/delete")
async def delete_project(
    project_id: str,
    confirm_name: str = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Delete a project. Requires typing the project name to confirm. Admin only."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.ORG_ADMIN):
        raise HTTPException(403, f"Requires {OrgRole.ORG_ADMIN.value}, you have {ctx.role.value}")

    project = db.get_project(project_id)
    if not project or project.org_id != ctx.org_id:
        raise HTTPException(404, "Project not found")

    if confirm_name.strip().lower() != project.name.strip().lower():
        raise HTTPException(400, f"Confirmation failed. Type '{project.name}' to delete.")

    # Delete project data directory
    import shutil
    data_dir = Path("data") / ctx.org_id / project.slug
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)

    # Delete from persistent storage too
    azure_site = Path("/home/site")
    if azure_site.exists():
        persistent_dir = Path("/home/data/data") / ctx.org_id / project.slug
        if persistent_dir.exists():
            shutil.rmtree(persistent_dir, ignore_errors=True)

    # Delete schema file
    schema_path = Path("schemas/custom") / f"{project.slug}.json"
    if schema_path.exists():
        schema_path.unlink()

    db.delete_project(project_id)
    return {"status": "deleted", "name": project.name}


# ---------------------------------------------------------------------------
# Org Database provisioning status
# ---------------------------------------------------------------------------


@app.get("/api/orgs/{org_id}/db-status")
async def get_org_db_status(
    org_id: str,
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Return the provisioning status of the org's database."""
    ctx = await get_org_context(authorization, x_org_id)
    if ctx.org_id != org_id:
        raise HTTPException(403, "Cannot view another org's database status")
    org_db = db.get_org_database(org_id)
    if not org_db:
        return {"status": "sqlite", "message": "Using local SQLite storage"}
    return org_db.to_dict()


@app.post("/api/orgs/{org_id}/db-reprovision")
async def reprovision_org_db(
    org_id: str,
    background_tasks: BackgroundTasks,
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Retry provisioning for a failed org database. Admin only."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.ORG_ADMIN):
        raise HTTPException(403, f"Requires {OrgRole.ORG_ADMIN.value}, you have {ctx.role.value}")
    if ctx.org_id != org_id:
        raise HTTPException(403, "Cannot reprovision another org's database")

    org_db = db.get_org_database(org_id)
    if not org_db:
        raise HTTPException(404, "No database record found for this org")
    if org_db.status == "ready":
        raise HTTPException(409, "Database is already provisioned and ready")
    if org_db.status == "provisioning":
        raise HTTPException(409, "Database provisioning is already in progress")

    db.update_org_database_status(org_id, status="provisioning", error=None)
    background_tasks.add_task(_provision_org_db, org_id)
    return {"status": "provisioning", "message": "Re-provisioning started"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

@app.get("/api/schemas")
async def list_schemas(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """List all available document type schemas."""
    _ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.VIEWER)
    schemas = {}
    # Built-in schemas (global, read-only)
    for path in sorted(SCHEMAS_DIR.glob("*.json")):
        schemas[path.stem] = {"builtin": True}
    # Org-specific custom schemas
    for path in sorted(paths.custom_schemas.glob("*.json")):
        schemas[path.stem] = {"builtin": False}
    return schemas


@app.get("/api/schemas/{doc_type}")
async def get_schema(
    doc_type: str,
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Get a specific schema by document type."""
    _ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.VIEWER)
    for parent in [SCHEMAS_DIR, paths.custom_schemas]:
        path = parent / f"{doc_type}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    raise HTTPException(404, f"Schema not found: {doc_type}")


@app.post("/api/schemas/{doc_type}")
async def save_custom_schema(
    doc_type: str,
    schema: dict,
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Save a custom schema. Business users can create new; only dev+ can overwrite."""
    ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.BUSINESS_USER)
    path = paths.custom_schemas / f"{doc_type}.json"

    # Business users can create new schemas but not overwrite existing ones
    if path.exists() and ctx.role == OrgRole.BUSINESS_USER:
        raise HTTPException(403, "Business users cannot edit existing schemas")

    paths.custom_schemas.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(schema, f, indent=2)
    return {"status": "saved", "path": str(path)}


# ---------------------------------------------------------------------------
# Upload & Extract
# ---------------------------------------------------------------------------

@app.post("/api/extract")
async def extract_pdf(
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    custom_schema: str = Form(None),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Upload a PDF, run Doc Intel + extraction, return structured data."""
    ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.BUSINESS_USER)

    upload_path = paths.uploads / file.filename
    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Load schema
    if custom_schema:
        schema = json.loads(custom_schema)
    else:
        schema_path = SCHEMAS_DIR / f"{doc_type}.json"
        if not schema_path.exists():
            schema_path = paths.custom_schemas / f"{doc_type}.json"
        if not schema_path.exists():
            raise HTTPException(404, f"No schema for type: {doc_type}")
        with open(schema_path) as f:
            schema = json.load(f)

    # Run Azure Document Intelligence
    try:
        raw = analyze_document(str(upload_path))
    except EnvironmentError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        raise HTTPException(500, f"Document Intelligence error: {e}")

    # Cache the raw result (org-scoped)
    cache_result(doc_type, upload_path.stem, raw, base_dir=paths.cache)

    # Run extraction
    try:
        result = extract(raw, doc_type, schema)
    except Exception as e:
        raise HTTPException(500, f"Extraction error: {e}")

    # Save result
    result_path = paths.results / f"{upload_path.stem}.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    return {
        "extracted": result,
        "schema": schema,
        "source_file": file.filename,
        "doc_type": doc_type,
    }


# ---------------------------------------------------------------------------
# Ground Truth management
# ---------------------------------------------------------------------------

@app.get("/api/ground-truth")
async def list_ground_truth(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """List all ground truth document sets."""
    _ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.VIEWER)
    docs = []
    if not paths.ground_truth.exists():
        return docs
    for type_dir in sorted(paths.ground_truth.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith("."):
            continue
        for pdf in sorted(type_dir.glob("*.pdf")):
            truth = pdf.with_suffix(".json")
            docs.append({
                "doc_type": type_dir.name,
                "name": pdf.stem,
                "has_truth_json": truth.exists(),
                "has_cache": get_cached_result(type_dir.name, pdf.stem, base_dir=paths.cache) is not None,
            })
    return docs


@app.post("/api/ground-truth")
async def upload_ground_truth(
    pdf: UploadFile = File(...),
    truth_json: UploadFile = File(...),
    doc_type: str = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Upload a ground truth document (PDF + known-correct JSON)."""
    ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.BUSINESS_USER)
    type_dir = paths.ground_truth / doc_type
    type_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(pdf.filename).stem

    pdf_path = type_dir / f"{stem}.pdf"
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(pdf.file, f)

    truth_path = type_dir / f"{stem}.json"
    content = await truth_json.read()
    try:
        json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, "truth_json must be valid JSON")
    with open(truth_path, "wb") as f:
        f.write(content)

    return {
        "status": "uploaded",
        "doc_type": doc_type,
        "name": stem,
        "pdf_path": str(pdf_path),
        "truth_path": str(truth_path),
    }


@app.post("/api/cache")
async def cache_ground_truth(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Run Azure Doc Intel on all uncached ground truth PDFs."""
    ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.BUSINESS_USER)
    results = []
    if not paths.ground_truth.exists():
        return results
    for type_dir in sorted(paths.ground_truth.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith("."):
            continue
        for pdf in sorted(type_dir.glob("*.pdf")):
            name = pdf.stem
            doc_type = type_dir.name
            cached = get_cached_result(doc_type, name, base_dir=paths.cache)
            if cached is not None:
                results.append({"name": name, "doc_type": doc_type, "status": "already_cached"})
                continue
            try:
                raw = analyze_document(str(pdf))
                cache_result(doc_type, name, raw, base_dir=paths.cache)
                results.append({"name": name, "doc_type": doc_type, "status": "cached"})
            except Exception as e:
                results.append({"name": name, "doc_type": doc_type, "status": f"error: {e}"})
    return results


# ---------------------------------------------------------------------------
# Generate schema from natural language description
# ---------------------------------------------------------------------------

@app.post("/api/generate-schema")
async def generate_schema(
    description: str = Form(...),
    doc_type_key: str = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Generate a JSON Schema from a plain-English description of desired fields."""
    ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.BUSINESS_USER)

    # Business users can generate new schemas but not overwrite existing
    existing_path = paths.custom_schemas / f"{doc_type_key}.json"
    if existing_path.exists() and ctx.role == OrgRole.BUSINESS_USER:
        raise HTTPException(403, "Business users cannot overwrite existing schemas")

    system = """You are a JSON Schema generator for document data extraction.
The user will describe fields they want extracted — often casually or with abbreviations.

Your job: interpret their intent and generate a valid JSON Schema.

Common abbreviations to expand:
- "org" → organization_name, "co" / "company" → company_name
- "web" / "url" → website, "email" / "mail" → email_address
- "phone" / "tel" → phone_number, "addr" / "address" → full_address
- "amt" / "amount" → amount, "qty" → quantity, "desc" → description
- "rev" → revenue, "yr" → year, "qtr" → quarter
- "dept" → department, "mgr" → manager, "emp" → employee

Schema rules:
- "type": "object" with "properties": { ... }
- Each field has "type" and "description"
- Supported types: string, number, array, object
- Use snake_case for field names
- For dates, use type "string" with description noting YYYY-MM-DD format
- For currency/money, use type "number"
- For arrays of objects (like line items), nest the item schema properly
- Add a clear description for each field so the extraction model knows what to look for

If the user's description is vague, make reasonable assumptions about
what fields would be useful for that document type.

Return ONLY the JSON Schema — no markdown fences, no explanation."""

    text = ""
    try:
        response = llm.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            temperature=0.0,
            system=system,
            messages=[{"role": "user", "content": description}],
        )
        text = response.content[0].text
        # Strip markdown fences if present
        cleaned = re.sub(r"^```\w*\n?", "", text.strip())
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
        schema = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                schema = json.loads(match.group())
            except json.JSONDecodeError:
                raise HTTPException(500, "Failed to parse generated schema")
        else:
            raise HTTPException(500, "Failed to parse generated schema")
    except Exception as e:
        logger.error(f"Schema generation error: {e}")
        raise HTTPException(500, f"Schema generation error: {e}")

    # Auto-save as custom schema
    paths.custom_schemas.mkdir(parents=True, exist_ok=True)
    path = paths.custom_schemas / f"{doc_type_key}.json"
    with open(path, "w") as f:
        json.dump(schema, f, indent=2)

    return {"schema": schema, "doc_type": doc_type_key, "saved_to": str(path)}


# ---------------------------------------------------------------------------
# Save corrected extraction as ground truth
# ---------------------------------------------------------------------------

@app.post("/api/save-as-ground-truth")
async def save_as_ground_truth(
    source_file: str = Form(...),
    doc_type: str = Form(...),
    corrected_json: str = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Save a corrected extraction result as ground truth."""
    ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.BUSINESS_USER)
    try:
        truth_data = json.loads(corrected_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "corrected_json must be valid JSON")

    source_path = paths.uploads / source_file
    if not source_path.exists():
        raise HTTPException(404, f"Source PDF not found in uploads: {source_file}")

    stem = source_path.stem

    type_dir = paths.ground_truth / doc_type
    type_dir.mkdir(parents=True, exist_ok=True)

    gt_pdf_path = type_dir / f"{stem}.pdf"
    shutil.copy2(source_path, gt_pdf_path)

    gt_json_path = type_dir / f"{stem}.json"
    with open(gt_json_path, "w") as f:
        json.dump(truth_data, f, indent=2)

    return {
        "status": "saved",
        "doc_type": doc_type,
        "name": stem,
        "pdf_path": str(gt_pdf_path),
        "truth_path": str(gt_json_path),
    }


# ---------------------------------------------------------------------------
# SQL Generation & Database Upload
# ---------------------------------------------------------------------------

@app.post("/api/generate-sql")
async def api_generate_sql(
    extracted_json: str = Form(...),
    table_name: str = Form(...),
    dialect: str = Form("mssql"),
    schema_name: str = Form("dbo"),
    include_ddl: bool = Form(False),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Generate SQL INSERT (and optionally CREATE TABLE) from extracted JSON."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.BUSINESS_USER):
        raise HTTPException(403, f"Requires {OrgRole.BUSINESS_USER.value}, you have {ctx.role.value}")
    try:
        data = json.loads(extracted_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    sql_parts = []
    if include_ddl:
        sql_parts.append(generate_create_table(data, table_name, dialect, schema_name))
        sql_parts.append("")
    sql_parts.append(json_to_sql(data, table_name, dialect, schema_name))

    return {"sql": "\n".join(sql_parts), "dialect": dialect, "table_name": table_name}


@app.post("/api/execute-sql")
async def api_execute_sql(
    sql: str = Form(...),
    connection_string: str = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Execute SQL against a database. Org admin only."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.ORG_ADMIN):
        raise HTTPException(403, f"Requires {OrgRole.ORG_ADMIN.value}, you have {ctx.role.value}")
    from sqlalchemy import create_engine, text

    try:
        engine = create_engine(connection_string, connect_args={"timeout": 30})
    except Exception as e:
        raise HTTPException(400, f"Invalid connection string: {e}")

    results = []
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    try:
        with engine.connect() as conn:
            for stmt in statements:
                try:
                    conn.execute(text(stmt))
                    results.append({"statement": stmt[:80] + "..." if len(stmt) > 80 else stmt, "status": "ok"})
                except Exception as e:
                    results.append({"statement": stmt[:80] + "..." if len(stmt) > 80 else stmt, "status": f"error: {e}"})
            conn.commit()
    except Exception as e:
        raise HTTPException(500, f"Database connection error: {e}")
    finally:
        engine.dispose()

    succeeded = sum(1 for r in results if r["status"] == "ok")
    return {"results": results, "succeeded": succeeded, "total": len(results)}


@app.post("/api/test-connection")
async def api_test_connection(
    connection_string: str = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Test a database connection."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.DEVELOPER):
        raise HTTPException(403, f"Requires {OrgRole.DEVELOPER.value}, you have {ctx.role.value}")
    from sqlalchemy import create_engine, text

    try:
        engine = create_engine(connection_string, connect_args={"timeout": 10})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return {"status": "ok", "message": "Connection successful"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@app.post("/api/evaluate")
async def run_evaluation(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Run the full evaluation pipeline and return results."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.DEVELOPER):
        raise HTTPException(403, f"Requires {OrgRole.DEVELOPER.value}, you have {ctx.role.value}")
    try:
        result = subprocess.run(
            ["uv", "run", "evaluate.py"],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            timeout=300,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Evaluation timed out (5 min limit)")
    except Exception as e:
        raise HTTPException(500, f"Evaluation error: {e}")


# ---------------------------------------------------------------------------
# Documents — simplified workflow
# ---------------------------------------------------------------------------


@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Upload a PDF. Returns extraction result."""
    ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.BUSINESS_USER)

    # Resolve project for doc_type
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    doc_type = project.slug

    # Save PDF
    try:
        pdf_path = paths.uploads / file.filename
        paths.uploads.mkdir(parents=True, exist_ok=True)
        content = await file.read()
        pdf_path.write_bytes(content)
    except Exception as e:
        logger.error("PDF save error: %s", e, exc_info=True)
        raise HTTPException(500, f"Failed to save PDF: {e}")

    # Run Doc Intel
    try:
        raw = analyze_document(str(pdf_path))
    except Exception as e:
        logger.error("Doc Intel error: %s", e, exc_info=True)
        raise HTTPException(500, f"Document Intelligence failed: {e}")

    # Cache the raw result
    try:
        cache_dir = paths.cache / doc_type
        cache_dir.mkdir(parents=True, exist_ok=True)
        stem = pdf_path.stem
        cache_path = cache_dir / f"{stem}.raw.json"
        with open(cache_path, "w") as f:
            json.dump(raw, f, indent=2)
    except Exception as e:
        logger.warning("Cache write error (non-fatal): %s", e)

    # Load schema
    schema = {}
    schema_path = paths.custom_schemas / f"{doc_type}.json"
    if schema_path.exists():
        schema = json.loads(schema_path.read_text())
    else:
        global_schema_path = GLOBAL_SCHEMAS_DIR / f"{doc_type}.json"
        if global_schema_path.exists():
            schema = json.loads(global_schema_path.read_text())

    # Run extraction
    try:
        extracted = extract(raw, doc_type, schema)
    except Exception as e:
        logger.error("Extraction error: %s", e, exc_info=True)
        raise HTTPException(500, f"Extraction failed: {e}")

    # Auto-index into Knowledge Base
    kb_id = kb.resolve_kb_id(ctx.org_id, project_id)
    try:
        kb.index_document(kb_id, doc_type, extracted, file.filename)
    except Exception:
        pass  # indexing failure shouldn't block extraction

    return {
        "extracted": extracted,
        "schema": schema,
        "source_file": file.filename,
        "doc_type": doc_type,
        "has_ground_truth": False,
    }


@app.post("/api/documents/correct")
async def save_document_corrections(
    project_id: str = Form(default=""),
    source_file: str = Form(...),
    doc_type: str = Form(...),
    corrected_json: str = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Save user corrections as ground truth and start optimization."""
    ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.BUSINESS_USER)
    try:
        corrected = json.loads(corrected_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    # Save corrected data as ground truth
    stem = Path(source_file).stem
    gt_dir = paths.ground_truth / doc_type
    gt_dir.mkdir(parents=True, exist_ok=True)
    (gt_dir / f"{stem}.json").write_text(json.dumps(corrected, indent=2))

    # Copy the source PDF to ground truth if not already there
    src_pdf = paths.uploads / source_file
    if src_pdf.exists():
        (gt_dir / f"{stem}.pdf").write_bytes(src_pdf.read_bytes())

    # Re-index with corrected data into KB
    kb_id = kb.resolve_kb_id(ctx.org_id, project_id or "")
    try:
        kb.index_document(kb_id, doc_type, corrected, source_file)
    except Exception:
        pass

    # Start optimization
    project = db.get_project(project_id) if project_id else None
    slug = project.slug if project else doc_type
    run_id = await _start_optimization_bg(ctx.org_id, project_id, slug)

    return {"status": "saved", "optimization_started": True, "run_id": run_id}


async def _start_optimization_bg(org_id: str, project_id: str, slug: str) -> str:
    """Create a Wiggum optimization run. Returns run_id."""
    import uuid
    from wiggum_trigger import is_github_configured

    run_id = str(uuid.uuid4())
    branch = f"clients/{org_id[:8]}-{slug}"

    db.create_wiggum_run(
        id=run_id,
        org_id=org_id,
        project_id=project_id,
        branch=branch,
        cycles=5,
        experiments=5,
        model="claude-sonnet-4-20250514",
    )

    if is_github_configured():
        from wiggum_trigger import commit_ground_truth_to_branch, trigger_workflow
        try:
            data_dir = str(Path("data") / org_id / slug)
            commit_ground_truth_to_branch(data_dir, branch, run_id)
            trigger_workflow(branch, 5, 5, "claude-sonnet-4-20250514", org_id, project_id, run_id)
            db.update_wiggum_run(run_id, status="queued")
        except Exception:
            db.update_wiggum_run(run_id, status="failed", completed_at=datetime.now(timezone.utc).isoformat())
    else:
        # No GitHub configured — mark as complete immediately
        db.update_wiggum_run(run_id, status="completed", completed_at=datetime.now(timezone.utc).isoformat())

    return run_id


@app.get("/api/projects/{project_id}/schema")
async def get_project_schema(
    project_id: str,
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Get the schema for a specific project."""
    ctx, paths = await _get_auth(authorization, x_org_id, x_project_id, OrgRole.VIEWER)
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    doc_type = project.slug
    schema_path = paths.custom_schemas / f"{doc_type}.json"
    if schema_path.exists():
        return json.loads(schema_path.read_text())

    global_path = GLOBAL_SCHEMAS_DIR / f"{doc_type}.json"
    if global_path.exists():
        return json.loads(global_path.read_text())

    return {"properties": {}, "type": "object"}


@app.post("/api/wiggum/start-background")
async def start_background_optimization(
    project_id: str = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Start Wiggum optimization with sensible defaults."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.DEVELOPER):
        raise HTTPException(403, f"Requires {OrgRole.DEVELOPER.value}, you have {ctx.role.value}")
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    run_id = await _start_optimization_bg(ctx.org_id, project_id, project.slug)
    return {"status": "started", "project_id": project_id, "run_id": run_id}


@app.get("/api/projects/{project_id}/extraction-status")
async def get_extraction_status(
    project_id: str,
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
):
    """Check if a project has been optimized (subsequent uploads skip the loop)."""
    ctx = await get_org_context(authorization, x_org_id)
    latest = db.get_latest_wiggum_run(ctx.org_id, project_id)
    if latest and latest.status == "completed":
        return {
            "optimized": True,
            "best_accuracy": latest.best_accuracy,
            "completed_at": latest.completed_at,
        }
    if latest and latest.status in ("pending", "queued", "in_progress"):
        return {
            "optimized": False,
            "optimizing": True,
            "status": latest.status,
            "best_accuracy": latest.best_accuracy,
        }
    return {"optimized": False, "optimizing": False, "best_accuracy": None}


# ---------------------------------------------------------------------------
# Knowledge Base (RAG)
# ---------------------------------------------------------------------------

import knowledge_base as kb


def _check_kb_ready(org_id: str) -> None:
    """Raise 503 if the org's database is still being provisioned."""
    org_db = db.get_org_database(org_id)
    if org_db and org_db.status == "provisioning":
        raise HTTPException(
            status_code=503,
            detail="Database is still being provisioned. Please retry shortly.",
            headers={"Retry-After": "10"},
        )


@app.get("/api/kb/stats")
async def kb_stats(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Get knowledge base stats for the current org/project."""
    ctx = await get_org_context(authorization, x_org_id)
    _check_kb_ready(ctx.org_id)
    kb_id = kb.resolve_kb_id(ctx.org_id, x_project_id)
    return kb.get_stats(kb_id)


@app.get("/api/kb/schema")
async def kb_schema(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Get schema description for the knowledge base."""
    ctx = await get_org_context(authorization, x_org_id)
    _check_kb_ready(ctx.org_id)
    kb_id = kb.resolve_kb_id(ctx.org_id, x_project_id)
    return {"schema": kb.get_schema_description(kb_id)}


@app.post("/api/kb/index")
async def kb_index(
    doc_type: str = Form(...),
    extracted_json: str = Form(...),
    source_file: str = Form(default=""),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Index extracted data into the knowledge base."""
    ctx = await get_org_context(authorization, x_org_id)
    if not role_at_least(ctx.role, OrgRole.BUSINESS_USER):
        raise HTTPException(403, f"Requires {OrgRole.BUSINESS_USER.value}, you have {ctx.role.value}")
    _check_kb_ready(ctx.org_id)
    kb_id = kb.resolve_kb_id(ctx.org_id, x_project_id)
    try:
        data = json.loads(extracted_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    result = kb.index_document(kb_id, doc_type, data, source_file)
    return {
        "table": result.table_name,
        "rows_inserted": result.rows_inserted,
        "child_tables": result.child_tables,
    }


@app.post("/api/kb/query")
async def kb_query(
    question: str = Form(...),
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Ask a natural language question about the knowledge base."""
    ctx = await get_org_context(authorization, x_org_id)
    _check_kb_ready(ctx.org_id)
    kb_id = kb.resolve_kb_id(ctx.org_id, x_project_id)
    result = kb.query(kb_id, question)
    return {
        "question": result.question,
        "sql": result.sql_generated,
        "results": result.raw_results[:50],
        "answer": result.answer,
        "error": result.error,
    }
