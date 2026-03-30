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

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from auth import (
    OrgContext,
    OrgPaths,
    OrgRole,
    require_at_least,
    resolve_org_paths,
)
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

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="autoPDF2SQLizer", version="0.1.0")

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


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        start = time.time()
        org_id = request.headers.get("x-org-id", "-")
        method = request.method
        path = request.url.path

        try:
            response = await call_next(request)
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            logger.error(
                f"{method} {path} → 500 UNHANDLED "
                f"({duration_ms:.0f}ms) org={org_id} error={e}"
            )
            raise

        duration_ms = (time.time() - start) * 1000
        if response.status_code >= 400:
            logger.warning(
                f"{method} {path} → {response.status_code} "
                f"({duration_ms:.0f}ms) org={org_id}"
            )
        else:
            logger.info(
                f"{method} {path} → {response.status_code} "
                f"({duration_ms:.0f}ms) org={org_id}"
            )
        return response


app.add_middleware(RequestLoggingMiddleware)

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


@app.get("/api/debug/generate-schema-test")
async def debug_schema_test():
    """Debug: test schema generation without auth."""
    import traceback
    try:
        response = llm.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            temperature=0.0,
            system="Generate a JSON Schema with type object and properties: year (number), quarter (string). Return ONLY JSON.",
            messages=[{"role": "user", "content": "year and quarter fields"}],
        )
        text = response.content[0].text
        cleaned = re.sub(r"^```\w*\n?", "", text.strip())
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
        schema = json.loads(cleaned)
        return {"status": "ok", "schema": schema}
    except json.JSONDecodeError as e:
        return {"status": "json_error", "raw_text": text, "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}


@app.get("/api/debug/auth-test")
async def debug_auth_test(
    authorization: str = Header(default=""),
    x_org_id: str = Header(default=""),
    x_project_id: str = Header(default=""),
):
    """Debug: trace the full auth flow and report where it fails."""
    import traceback
    steps = {}

    # Step 1: get_current_user
    try:
        user = await get_current_user(authorization)
        steps["1_user"] = {"sub": user.sub, "email": user.email, "name": user.name}
    except Exception as e:
        steps["1_user"] = {"error": str(e), "tb": traceback.format_exc()}
        return steps

    # Step 2: get_org_context
    try:
        ctx = await get_org_context(authorization, x_org_id)
        steps["2_org_context"] = {"org_id": ctx.org_id, "role": ctx.role.value}
    except Exception as e:
        steps["2_org_context"] = {"error": str(e), "tb": traceback.format_exc()}
        return steps

    # Step 3: resolve_org_paths
    try:
        paths = await resolve_org_paths(authorization, x_org_id, x_project_id)
        steps["3_paths"] = {
            "schemas": str(paths.schemas),
            "custom_schemas": str(paths.custom_schemas),
            "ground_truth": str(paths.ground_truth),
            "uploads": str(paths.uploads),
        }
    except Exception as e:
        steps["3_paths"] = {"error": str(e), "tb": traceback.format_exc()}
        return steps

    steps["status"] = "all_ok"
    return steps


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
from auth import get_current_user, get_org_context
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.ORG_ADMIN)),
):
    """List pending join requests for the current org. Admin only."""
    return db.list_join_requests(ctx.org_id, status="pending")


@app.post("/api/orgs/requests/{request_id}/resolve")
async def resolve_join_request(
    request_id: str,
    approve: bool = Form(...),
    ctx: OrgContext = Depends(require_at_least(OrgRole.ORG_ADMIN)),
):
    """Approve or reject a join request. Admin only."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.VIEWER)),
):
    """List projects in the current org. Admins see all; others see assigned only."""
    is_admin = ctx.role == OrgRole.ORG_ADMIN
    return db.list_projects(ctx.org_id, ctx.user.sub, is_admin)


@app.post("/api/projects")
async def create_project(
    name: str = Form(...),
    slug: str = Form(...),
    description: str = Form(""),
    ctx: OrgContext = Depends(require_at_least(OrgRole.ORG_ADMIN)),
):
    """Create a new project in the current org. Admin only."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.VIEWER)),
):
    """Get project details + members."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.ORG_ADMIN)),
):
    """Add a member to a project. Admin only."""
    project = db.get_project(project_id)
    if not project or project.org_id != ctx.org_id:
        raise HTTPException(404, "Project not found")

    db.add_project_member(project_id, user_sub, user_email, ctx.user.sub)
    return {"status": "added", "project_id": project_id, "user_sub": user_sub}


@app.delete("/api/projects/{project_id}/members/{user_sub}")
async def remove_project_member(
    project_id: str,
    user_sub: str,
    ctx: OrgContext = Depends(require_at_least(OrgRole.ORG_ADMIN)),
):
    """Remove a member from a project. Admin only."""
    db.remove_project_member(project_id, user_sub)
    return {"status": "removed"}


# ---------------------------------------------------------------------------
# Org Database provisioning status
# ---------------------------------------------------------------------------


@app.get("/api/orgs/{org_id}/db-status")
async def get_org_db_status(
    org_id: str,
    ctx: OrgContext = Depends(require_at_least(OrgRole.VIEWER)),
):
    """Return the provisioning status of the org's database."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.ORG_ADMIN)),
):
    """Retry provisioning for a failed org database. Admin only."""
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
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """List all available document type schemas."""
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
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """Get a specific schema by document type."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER)),
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """Save a custom schema. Business users can create new; only dev+ can overwrite."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER)),
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """Upload a PDF, run Doc Intel + extraction, return structured data."""

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
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """List all ground truth document sets."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER)),
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """Upload a ground truth document (PDF + known-correct JSON)."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER)),
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """Run Azure Doc Intel on all uncached ground truth PDFs."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER)),
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """Generate a JSON Schema from a plain-English description of desired fields."""

    # Business users can generate new schemas but not overwrite existing
    existing_path = paths.custom_schemas / f"{doc_type_key}.json"
    if existing_path.exists() and ctx.role == OrgRole.BUSINESS_USER:
        raise HTTPException(403, "Business users cannot overwrite existing schemas")

    system = """You are a JSON Schema generator. The user will describe what fields
they want to extract from a document. Generate a valid JSON Schema with:
- "type": "object"
- "properties": { ... } with each field having "type" and "description"
- Supported types: string, number, array, object

Use snake_case for field names. For dates, use type "string" with a
description noting YYYY-MM-DD format. For arrays of objects, nest
the item schema properly.

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
    ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER)),
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """Save a corrected extraction result as ground truth."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER)),
):
    """Generate SQL INSERT (and optionally CREATE TABLE) from extracted JSON."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.ORG_ADMIN)),
):
    """Execute SQL against a database. Org admin only."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.DEVELOPER)),
):
    """Test a database connection."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.DEVELOPER)),
):
    """Run the full evaluation pipeline and return results."""
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
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    project_id: str = Form(...),
    ground_truth: UploadFile | None = File(default=None),
    ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER)),
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """Upload a PDF and optionally a ground truth file. Returns extraction result."""
    from process import extract
    from doc_intel import analyze_document

    # Resolve project for doc_type
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    doc_type = project.slug

    # Save PDF
    pdf_path = paths.uploads / file.filename
    paths.uploads.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    pdf_path.write_bytes(content)

    # Run Doc Intel
    raw = analyze_document(str(pdf_path))

    # Cache the raw result
    cache_dir = paths.cache / doc_type
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    cache_path = cache_dir / f"{stem}.raw.json"
    with open(cache_path, "w") as f:
        json.dump(raw, f, indent=2)

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
    extracted = extract(raw, doc_type, schema)

    # Auto-index into Knowledge Base
    kb_id = kb.resolve_kb_id(ctx.org_id, project_id)
    try:
        kb.index_document(kb_id, doc_type, extracted, file.filename)
    except Exception:
        pass  # indexing failure shouldn't block extraction

    has_ground_truth = ground_truth is not None
    result = {
        "extracted": extracted,
        "schema": schema,
        "source_file": file.filename,
        "doc_type": doc_type,
        "has_ground_truth": has_ground_truth,
    }

    if has_ground_truth:
        # Path A: save ground truth and trigger optimization
        gt_content = await ground_truth.read()
        gt_dir = paths.ground_truth / doc_type
        gt_dir.mkdir(parents=True, exist_ok=True)

        # Save the PDF and truth JSON as ground truth
        (gt_dir / f"{stem}.pdf").write_bytes(content)
        (gt_dir / f"{stem}.json").write_bytes(gt_content)

        # Start optimization in background
        background_tasks.add_task(_start_optimization_bg, ctx.org_id, project_id, project.slug)
        result["optimization_started"] = True

    return result


@app.post("/api/documents/correct")
async def save_document_corrections(
    background_tasks: BackgroundTasks,
    project_id: str = Form(default=""),
    source_file: str = Form(...),
    doc_type: str = Form(...),
    corrected_json: str = Form(...),
    ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER)),
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """Save user corrections as ground truth and start optimization."""
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

    # Start optimization in background
    project = db.get_project(project_id) if project_id else None
    slug = project.slug if project else doc_type
    background_tasks.add_task(_start_optimization_bg, ctx.org_id, project_id, slug)

    return {"status": "saved", "optimization_started": True}


async def _start_optimization_bg(org_id: str, project_id: str, slug: str):
    """Background task: start Wiggum optimization with sensible defaults."""
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
        except Exception as e:
            db.update_wiggum_run(run_id, status="failed", completed_at=datetime.now(timezone.utc).isoformat())
    else:
        # No GitHub configured — mark as complete (server-side loop not yet implemented)
        db.update_wiggum_run(run_id, status="completed", completed_at=datetime.now(timezone.utc).isoformat())


@app.get("/api/projects/{project_id}/schema")
async def get_project_schema(
    project_id: str,
    ctx: OrgContext = Depends(require_at_least(OrgRole.VIEWER)),
    paths: OrgPaths = Depends(resolve_org_paths),
):
    """Get the schema for a specific project."""
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
    background_tasks: BackgroundTasks,
    project_id: str = Form(...),
    ctx: OrgContext = Depends(require_at_least(OrgRole.DEVELOPER)),
):
    """Start Wiggum optimization with sensible defaults."""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    background_tasks.add_task(_start_optimization_bg, ctx.org_id, project_id, project.slug)
    return {"status": "started", "project_id": project_id}


@app.get("/api/projects/{project_id}/extraction-status")
async def get_extraction_status(
    project_id: str,
    ctx: OrgContext = Depends(require_at_least(OrgRole.VIEWER)),
):
    """Check if a project has been optimized (subsequent uploads skip the loop)."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.VIEWER)),
    x_project_id: str = Header(default=""),
):
    """Get knowledge base stats for the current org/project."""
    _check_kb_ready(ctx.org_id)
    kb_id = kb.resolve_kb_id(ctx.org_id, x_project_id)
    return kb.get_stats(kb_id)


@app.get("/api/kb/schema")
async def kb_schema(
    ctx: OrgContext = Depends(require_at_least(OrgRole.VIEWER)),
    x_project_id: str = Header(default=""),
):
    """Get schema description for the knowledge base."""
    _check_kb_ready(ctx.org_id)
    kb_id = kb.resolve_kb_id(ctx.org_id, x_project_id)
    return {"schema": kb.get_schema_description(kb_id)}


@app.post("/api/kb/index")
async def kb_index(
    doc_type: str = Form(...),
    extracted_json: str = Form(...),
    source_file: str = Form(default=""),
    ctx: OrgContext = Depends(require_at_least(OrgRole.BUSINESS_USER)),
    x_project_id: str = Header(default=""),
):
    """Index extracted data into the knowledge base."""
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
    ctx: OrgContext = Depends(require_at_least(OrgRole.VIEWER)),
    x_project_id: str = Header(default=""),
):
    """Ask a natural language question about the knowledge base."""
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
