"""
autoPDF2SQLizer — FastAPI web application.
Upload PDFs, select document types, define schemas, manage ground truth,
and run extraction + evaluation.

Usage:
    uv run uvicorn app:app --reload --port 8000
"""

import json
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from doc_intel import analyze_document, cache_result, get_cached_result
from process import extract

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
SCHEMAS_DIR = BASE_DIR / "schemas"
CUSTOM_SCHEMAS_DIR = SCHEMAS_DIR / "custom"
GROUND_TRUTH_DIR = BASE_DIR / "ground_truth"
UPLOADS_DIR = BASE_DIR / "uploads"
RESULTS_DIR = BASE_DIR / "results"

for d in [CUSTOM_SCHEMAS_DIR, GROUND_TRUTH_DIR, UPLOADS_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="autoPDF2SQLizer", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/")
async def index():
    return FileResponse(str(BASE_DIR / "static" / "index.html"))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

@app.get("/api/schemas")
async def list_schemas():
    """List all available document type schemas."""
    schemas = {}
    for path in sorted(SCHEMAS_DIR.glob("*.json")):
        schemas[path.stem] = {"builtin": True}
    for path in sorted(CUSTOM_SCHEMAS_DIR.glob("*.json")):
        schemas[path.stem] = {"builtin": False}
    return schemas


@app.get("/api/schemas/{doc_type}")
async def get_schema(doc_type: str):
    """Get a specific schema by document type."""
    for parent in [SCHEMAS_DIR, CUSTOM_SCHEMAS_DIR]:
        path = parent / f"{doc_type}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    raise HTTPException(404, f"Schema not found: {doc_type}")


@app.post("/api/schemas/{doc_type}")
async def save_custom_schema(doc_type: str, schema: dict):
    """Save a custom schema for a new document type."""
    CUSTOM_SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    path = CUSTOM_SCHEMAS_DIR / f"{doc_type}.json"
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
):
    """Upload a PDF, run Doc Intel + extraction, return structured data."""

    # Save uploaded file
    upload_path = UPLOADS_DIR / file.filename
    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Load schema
    if custom_schema:
        schema = json.loads(custom_schema)
    else:
        schema_path = SCHEMAS_DIR / f"{doc_type}.json"
        if not schema_path.exists():
            schema_path = CUSTOM_SCHEMAS_DIR / f"{doc_type}.json"
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

    # Run extraction
    try:
        result = extract(raw, doc_type, schema)
    except Exception as e:
        raise HTTPException(500, f"Extraction error: {e}")

    # Save result
    result_path = RESULTS_DIR / f"{upload_path.stem}.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    return {
        "extracted": result,
        "schema": schema,
        "source_file": file.filename,
    }


# ---------------------------------------------------------------------------
# Ground Truth management
# ---------------------------------------------------------------------------

@app.get("/api/ground-truth")
async def list_ground_truth():
    """List all ground truth document sets."""
    docs = []
    if not GROUND_TRUTH_DIR.exists():
        return docs
    for type_dir in sorted(GROUND_TRUTH_DIR.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith("."):
            continue
        for pdf in sorted(type_dir.glob("*.pdf")):
            truth = pdf.with_suffix(".json")
            docs.append({
                "doc_type": type_dir.name,
                "name": pdf.stem,
                "has_truth_json": truth.exists(),
                "has_cache": get_cached_result(type_dir.name, pdf.stem) is not None,
            })
    return docs


@app.post("/api/ground-truth")
async def upload_ground_truth(
    pdf: UploadFile = File(...),
    truth_json: UploadFile = File(...),
    doc_type: str = Form(...),
):
    """Upload a ground truth document (PDF + known-correct JSON)."""
    type_dir = GROUND_TRUTH_DIR / doc_type
    type_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(pdf.filename).stem

    pdf_path = type_dir / f"{stem}.pdf"
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(pdf.file, f)

    truth_path = type_dir / f"{stem}.json"
    content = await truth_json.read()
    # Validate it's valid JSON
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
async def cache_ground_truth():
    """Run Azure Doc Intel on all uncached ground truth PDFs."""
    results = []
    for type_dir in sorted(GROUND_TRUTH_DIR.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith("."):
            continue
        for pdf in sorted(type_dir.glob("*.pdf")):
            name = pdf.stem
            doc_type = type_dir.name
            cached = get_cached_result(doc_type, name)
            if cached is not None:
                results.append({"name": name, "doc_type": doc_type, "status": "already_cached"})
                continue
            try:
                raw = analyze_document(str(pdf))
                cache_result(doc_type, name, raw)
                results.append({"name": name, "doc_type": doc_type, "status": "cached"})
            except Exception as e:
                results.append({"name": name, "doc_type": doc_type, "status": f"error: {e}"})
    return results


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@app.post("/api/evaluate")
async def run_evaluation():
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
