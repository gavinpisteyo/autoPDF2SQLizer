"""
Azure Document Intelligence wrapper.
DO NOT MODIFY — this is the fixed document analysis layer.

Calls Azure's prebuilt-layout model to extract text, tables, and
key-value pairs from PDFs. Results are cached to avoid re-calling
the API during Wiggum loop iterations.
"""

import json
import os
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"


def analyze_document(pdf_path: str) -> dict:
    """
    Analyze a PDF using Azure Document Intelligence (prebuilt-layout).
    Returns the raw analyzeResult as a dict.
    """
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
    from azure.core.credentials import AzureKeyCredential

    endpoint = os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "")
    key = os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_KEY", "")

    if not endpoint or not key:
        raise EnvironmentError(
            "Set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and "
            "AZURE_DOCUMENT_INTELLIGENCE_KEY in your .env file."
        )

    client = DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key),
    )

    with open(pdf_path, "rb") as f:
        poller = client.begin_analyze_document(
            "prebuilt-layout",
            body=f,
            content_type="application/pdf",
        )

    result = poller.result()
    return result.as_dict()


def cache_result(doc_type: str, doc_name: str, result: dict) -> Path:
    """Save a Document Intelligence result to the cache."""
    cache_dir = CACHE_DIR / doc_type
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{doc_name}.raw.json"
    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)
    return cache_path


def get_cached_result(doc_type: str, doc_name: str) -> dict | None:
    """Load a cached Document Intelligence result, or None."""
    cache_path = CACHE_DIR / doc_type / f"{doc_name}.raw.json"
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)
    return None
