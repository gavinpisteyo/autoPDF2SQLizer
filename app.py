"""
autoPDF2SQLizer — FastAPI web application.
Upload PDFs, select document types, define schemas, manage ground truth,
and run extraction + evaluation.

Usage:
    uv run uvicorn app:app --reload --port 8000
"""

import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

        response = await call_next(request)

        duration_ms = (time.time() - start) * 1000
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
    name: str = Form(...),
    authorization: str = Header(default=""),
):
    """Create a new organization. The creator becomes admin."""
    user = await get_current_user(authorization)
    org = db.create_org(name, user.sub, user.email, user.name)
    return org.to_dict()


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

    try:
        response = llm.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            temperature=0.0,
            system=system,
            messages=[{"role": "user", "content": description}],
        )
        text = response.content[0].text
        schema = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            schema = json.loads(match.group())
        else:
            raise HTTPException(500, "Failed to parse generated schema")
    except Exception as e:
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
