"""
Rell.io Notion API — slim read-only Notion proxy.

Standalone extraction of the /api/notion/* surface from
``tiapmaatzu-rell-io/api_server.py`` so the Soul Registry Studio can reach
the canonical Notion databases from a hosted frontend without shipping the
integration token to the browser.

Only read-only actions are exposed (status, sources, databases, schema,
query, page, search, digest). Write actions stay behind the orchestrator's
confirmed=true gate in the main API.

Auth mirrors api_server.py: requests must carry ``X-API-Token`` matching
one of the comma-separated ``ALLOWED_API_TOKENS`` env values. If no tokens
are configured the API is open (same behavior as the main service).
"""

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from notion_connector import NotionConnectorSubagent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rellio-notion-api")

app = FastAPI(title="Rell.io Notion API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_TOKEN_HEADER = "X-API-Token"
_allowed_tokens: set = {
    t.strip()
    for t in os.environ.get("ALLOWED_API_TOKENS", "").split(",")
    if t.strip()
}

connector = NotionConnectorSubagent()

_READ_ONLY_ACTIONS = {
    "status", "sources", "databases", "schema", "query", "page",
    "search", "digest",
}


def auth(request: Request) -> None:
    token = request.headers.get(API_TOKEN_HEADER, "")
    if _allowed_tokens and token not in _allowed_tokens:
        raise HTTPException(status_code=401, detail="Invalid API token")


def _read_only(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if action not in _READ_ONLY_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Notion action '{action}' is not exposed via the API. "
                   f"Read-only actions: {sorted(_READ_ONLY_ACTIONS)}")
    return connector.execute({"action": action, **params})


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "app": "Rell.io Notion API", "version": "1.0.0"}


@app.get("/api/health")
def api_health() -> Dict[str, Any]:
    return health()


@app.get("/api/notion/status", dependencies=[Depends(auth)])
def notion_status() -> Dict[str, Any]:
    """Token configuration + bot identity + registered database ids."""
    return _read_only("status", {})


@app.get("/api/notion/sources", dependencies=[Depends(auth)])
def notion_sources() -> Dict[str, Any]:
    """Canonical Notion source registry (titles, URLs, data sources, access)."""
    return _read_only("sources", {})


@app.get("/api/notion/databases", dependencies=[Depends(auth)])
def notion_databases() -> Dict[str, Any]:
    """Live status of every registered database (title, url, property count)."""
    return _read_only("databases", {})


@app.get("/api/notion/databases/{database}/schema", dependencies=[Depends(auth)])
def notion_database_schema(database: str) -> Dict[str, Any]:
    """Property schema (names, types, select options) for one database."""
    return _read_only("schema", {"database": database})


class NotionQueryIn(BaseModel):
    database: str = Field(..., description="Database key or raw Notion id")
    filter: Optional[Dict[str, Any]] = Field(None, description="Notion filter object")
    sorts: Optional[List[Dict[str, Any]]] = Field(None, description="Notion sorts array")
    page_size: int = Field(25, ge=1, le=100)
    start_cursor: Optional[str] = Field(None, description="Pagination cursor")


@app.post("/api/notion/query", dependencies=[Depends(auth)])
def notion_query(payload: NotionQueryIn) -> Dict[str, Any]:
    """Query a database (read-only). Returns summarized pages + next_cursor."""
    return _read_only("query", payload.model_dump(exclude_none=True))


@app.get("/api/notion/pages/{page_id}", dependencies=[Depends(auth)])
def notion_page(page_id: str) -> Dict[str, Any]:
    """Fetch a single page's properties."""
    return _read_only("page", {"page_id": page_id})


@app.get("/api/notion/search", dependencies=[Depends(auth)])
def notion_search(q: str = "", page_size: int = 10) -> Dict[str, Any]:
    """Workspace search across pages/databases the integration can see."""
    return _read_only("search", {"query": q, "page_size": page_size})


@app.get("/api/notion/digest", dependencies=[Depends(auth)])
def notion_digest(days: int = 14) -> Dict[str, Any]:
    """Operational digest: overdue/due-soon tasks + upcoming calendar entries."""
    return _read_only("digest", {"days": days})
