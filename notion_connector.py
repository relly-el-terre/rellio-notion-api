"""
Notion Connector Subagent
=========================
Connects the Rell.io fleet to the canonical Notion databases:

- character_db      : Character Database
- content_calendar  : Content Calendar
- task_db           : Task Database

Token resolution order:
  1. NOTION_TOKEN environment variable
  2. NOTION_TOKEN_FILE environment variable (path)
  3. data/.notion_token (gitignored)

If no token is configured, all actions return a structured
``token_missing`` status instead of raising.

Read actions (status, databases, schema, query, page, search) are always
allowed. Write actions (create_page, update_page, create_database_page)
require ``confirmed=true`` in the input — same safety convention as the
deployment ops agent.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from base_subagent import BaseSubagent

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TIMEOUT = 30

DATABASES: Dict[str, str] = {
    "character_db": "eb313c140e1c82d2864d014561edc595",
    "character_db_alt": "3d313c140e1c819292fee0b0a6dbaa1b",
    "content_calendar": "3d313c140e1c81bea04be3b8c43bcf1f",
    "task_db": "3d313c140e1c816985c7ec963f4c8757",
}

# Canonical Notion source registry — the three stakeholder-facing databases
# plus the secondary character DB discovered via MCP. `data_source` is the
# Notion collection:// URL used by the hosted MCP query tools.
NOTION_SOURCES: Dict[str, Dict[str, Any]] = {
    "character_db": {
        "title": "Character Database (1)",
        "url": "https://app.notion.com/p/eb313c140e1c82d2864d014561edc595",
        "data_source": "collection://78213c14-0e1c-82d2-9cdb-876b4adcc109",
        "parent_page": "Gilded Mirrors Originals",
        "access": "mcp_only",
        "notes": "Primary character/soul registry (archetypes, attributes, "
                 "backstory, prompts, budgets). REST connector 404s until the "
                 "Tiapmaatzu Deployer integration is shared with it.",
    },
    "character_db_alt": {
        "title": "Character Database",
        "url": "https://app.notion.com/p/3d313c140e1c819292fee0b0a6dbaa1b",
        "data_source": None,
        "parent_page": "Gilded Mirrors Originals",
        "access": "mcp_only",
        "notes": "Secondary character database discovered via Notion MCP search.",
    },
    "content_calendar": {
        "title": "Content Calendar",
        "url": "https://app.notion.com/p/3d313c140e1c81bea04be3b8c43bcf1f",
        "data_source": "collection://3d313c14-0e1c-8122-a2a7-000bb477c4b7",
        "parent_page": "Gilded Mirrors Originals",
        "access": "integration+mcp",
        "notes": "Content scheduling: Title, Status, Priority, Content Type, "
                 "Publish Date, Tags, Assigned To.",
    },
    "task_db": {
        "title": "Task Database (Task List)",
        "url": "https://app.notion.com/p/3d313c140e1c816985c7ec963f4c8757",
        "data_source": "collection://3d313c14-0e1c-81ce-b449-000baf52a4a1",
        "parent_page": "Gilded Mirrors Originals",
        "access": "integration+mcp",
        "notes": "Task tracking: Task, Status, Priority (incl. Critical), "
                 "Category, Due Date, Assigned To.",
    },
}

WRITE_ACTIONS = {"create_page", "update_page", "archive_page"}


class NotionConnectorSubagent(BaseSubagent):
    """Read/write bridge to the canonical Notion databases."""

    def __init__(self, name: str = "NotionConnectorSubagent",
                 data_dir: Optional[Path] = None):
        super().__init__(name)
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).resolve().parent.parent / "data"

    # ------------------------------------------------------------------
    # Token handling
    # ------------------------------------------------------------------
    def _token(self) -> Optional[str]:
        token = os.environ.get("NOTION_TOKEN", "").strip()
        if token:
            return token
        token_file = os.environ.get("NOTION_TOKEN_FILE", "").strip()
        candidates = [Path(token_file)] if token_file else []
        candidates.append(self.data_dir / ".notion_token")
        for path in candidates:
            try:
                value = path.read_text().strip()
                if value:
                    return value
            except OSError:
                continue
        return None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str,
                 payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        token = self._token()
        if not token:
            return {"success": False, "status": "token_missing",
                    "error": "No Notion token configured (NOTION_TOKEN env, "
                             "NOTION_TOKEN_FILE, or data/.notion_token)."}
        try:
            req = urllib.request.Request(
                f"{NOTION_API}{path}",
                data=json.dumps(payload).encode() if payload is not None else None,
                headers=self._headers(), method=method)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read().decode()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            status = exc.code
            try:
                body = json.loads(raw)
            except ValueError:
                body = {"raw": raw[:500]}
            return {"success": False, "status": f"http_{status}",
                    "error": body.get("message") or body.get("code") or exc.reason,
                    "detail": body}
        except (urllib.error.URLError, OSError) as exc:
            return {"success": False, "status": "request_failed",
                    "error": str(exc)}
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {"raw": raw[:500]}
        return {"success": True, "data": body}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_db(raw: str) -> Optional[str]:
        key = str(raw or "").strip().lower()
        if key in DATABASES:
            return DATABASES[key]
        compact = key.replace("-", "").replace("_", "")
        for name, dbid in DATABASES.items():
            if compact in dbid.replace("-", ""):
                return dbid
        # raw database id or URL
        digits = "".join(c for c in key if c.isalnum())
        for dbid in DATABASES.values():
            if dbid.replace("-", "") in digits or digits in dbid.replace("-", ""):
                return dbid
        return None

    @staticmethod
    def _summarize_page(page: Dict[str, Any]) -> Dict[str, Any]:
        props = page.get("properties", {})
        title = ""
        for prop in props.values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "")
                                for t in prop.get("title", []))
                break
        return {
            "id": page.get("id"),
            "url": page.get("url"),
            "last_edited": page.get("last_edited_time"),
            "title": title,
            "archived": page.get("archived", False),
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        action = str(input_data.get("action") or input_data.get("notion_action") or "").strip()
        if not action:
            return {"success": False, "error": "Missing 'action'.",
                    "available_actions": sorted(self._actions())}
        if action in WRITE_ACTIONS and not input_data.get("confirmed"):
            return {"success": False, "error": f"'{action}' mutates Notion data and "
                    "requires confirmed=true."}
        handler = getattr(self, f"_action_{action}", None)
        if handler is None:
            return {"success": False,
                    "error": f"Unknown action '{action}'.",
                    "available_actions": sorted(self._actions())}
        try:
            return handler(input_data)
        except Exception as exc:  # defensive: never raise to caller
            logger.exception("Notion action %s failed", action)
            return {"success": False, "error": f"{action} failed: {exc}"}

    @staticmethod
    def _actions() -> List[str]:
        return [m[len("_action_"):] for m in dir(NotionConnectorSubagent)
                if m.startswith("_action_")]

    def _action_sources(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "action": "sources",
                "sources": NOTION_SOURCES}

    def _action_status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        token = self._token()
        result: Dict[str, Any] = {
            "success": True,
            "action": "status",
            "token_configured": bool(token),
            "token_source": ("env" if os.environ.get("NOTION_TOKEN") else
                             "file" if token else None),
            "databases": {k: {"id": v} for k, v in DATABASES.items()},
        }
        if token:
            me = self._request("GET", "/users/me")
            result["bot"] = me.get("data", {}).get("bot", {}) if me.get("success") else me
        return result

    def _action_databases(self, data: Dict[str, Any]) -> Dict[str, Any]:
        out = {}
        for key, dbid in DATABASES.items():
            res = self._request("GET", f"/databases/{dbid}")
            if res.get("success"):
                db = res["data"]
                out[key] = {
                    "id": db.get("id"),
                    "title": "".join(t.get("plain_text", "")
                                     for t in db.get("title", [])),
                    "url": db.get("url"),
                    "property_count": len(db.get("properties", {})),
                }
            else:
                out[key] = {"id": dbid, "error": res.get("error"),
                            "status": res.get("status")}
        return {"success": all("error" not in v for v in out.values()),
                "action": "databases", "databases": out}

    def _action_schema(self, data: Dict[str, Any]) -> Dict[str, Any]:
        dbid = self._resolve_db(str(data.get("database") or ""))
        if not dbid:
            return {"success": False, "error": "Unknown database. "
                    f"Use one of: {', '.join(DATABASES)} or a raw id."}
        res = self._request("GET", f"/databases/{dbid}")
        if not res.get("success"):
            return {**res, "action": "schema"}
        db = res["data"]
        props = {}
        for name, spec in db.get("properties", {}).items():
            entry = {"type": spec.get("type")}
            for kind in ("select", "multi_select", "status"):
                sub = spec.get(kind)
                if isinstance(sub, dict) and sub.get("options"):
                    entry["options"] = [
                        o.get("name") for o in sub["options"]
                        if isinstance(o, dict)]
            props[name] = entry
        return {"success": True, "action": "schema",
                "database": dbid,
                "title": "".join(t.get("plain_text", "") for t in db.get("title", [])),
                "properties": props}

    def _action_query(self, data: Dict[str, Any]) -> Dict[str, Any]:
        dbid = self._resolve_db(str(data.get("database") or ""))
        if not dbid:
            return {"success": False, "error": "Unknown database."}
        payload: Dict[str, Any] = {}
        for key in ("filter", "sorts"):
            if data.get(key):
                payload[key] = data[key]
        page_size = int(data.get("page_size") or 25)
        payload["page_size"] = max(1, min(page_size, 100))
        start_cursor = data.get("start_cursor")
        if start_cursor:
            payload["start_cursor"] = start_cursor
        res = self._request("POST", f"/databases/{dbid}/query", payload)
        if not res.get("success"):
            return {**res, "action": "query"}
        body = res["data"]
        return {"success": True, "action": "query",
                "database": dbid,
                "count": len(body.get("results", [])),
                "has_more": body.get("has_more", False),
                "next_cursor": body.get("next_cursor"),
                "pages": [self._summarize_page(p) for p in body.get("results", [])]}

    def _action_page(self, data: Dict[str, Any]) -> Dict[str, Any]:
        page_id = str(data.get("page_id") or "").strip()
        if not page_id:
            return {"success": False, "error": "Missing page_id."}
        res = self._request("GET", f"/pages/{page_id}")
        if not res.get("success"):
            return {**res, "action": "page"}
        return {"success": True, "action": "page",
                "page": self._summarize_page(res["data"]),
                "properties": res["data"].get("properties", {})}

    def _action_search(self, data: Dict[str, Any]) -> Dict[str, Any]:
        query = str(data.get("query") or "").strip()
        payload: Dict[str, Any] = {"page_size": min(int(data.get("page_size") or 10), 100)}
        if query:
            payload["query"] = query
        res = self._request("POST", "/search", payload)
        if not res.get("success"):
            return {**res, "action": "search"}
        return {"success": True, "action": "search",
                "count": len(res["data"].get("results", [])),
                "results": [{"id": r.get("id"), "object": r.get("object"),
                             "url": r.get("url")}
                            for r in res["data"].get("results", [])]}

    @staticmethod
    def _prop_value(page: Dict[str, Any], name: str) -> Any:
        """Extract a normalized value for a named Notion property."""
        prop = page.get("properties", {}).get(name)
        if not isinstance(prop, dict):
            return None
        ptype = prop.get("type")
        if ptype in ("title", "rich_text"):
            return "".join(t.get("plain_text", "")
                           for t in prop.get(ptype, []))
        if ptype in ("select", "status"):
            sub = prop.get(ptype) or {}
            return sub.get("name")
        if ptype == "multi_select":
            return [o.get("name") for o in prop.get(ptype, [])
                    if isinstance(o, dict)]
        if ptype == "date":
            return (prop.get("date") or {}).get("start")
        if ptype == "people":
            return [u.get("name") for u in prop.get(ptype, [])
                    if isinstance(u, dict)]
        return prop.get(ptype)

    @staticmethod
    def _date_part(value: Any) -> Optional[str]:
        """Reduce a Notion date/datetime value to 'YYYY-MM-DD'."""
        if not value:
            return None
        return str(value)[:10]

    def _action_digest(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Read-only operational digest: open tasks (overdue/due soon/
        backlog) plus upcoming Content Calendar entries."""
        from datetime import date, timedelta

        days = max(1, min(int(data.get("days") or 14), 90))
        today = date.today()
        horizon = (today + timedelta(days=days)).isoformat()
        today_s = today.isoformat()

        def fetch_all(db_key: str) -> List[Dict[str, Any]]:
            dbid = self._resolve_db(db_key)
            if not dbid:
                return []
            res = self._request("POST", f"/databases/{dbid}/query",
                                {"page_size": 100})
            if not res.get("success"):
                return []
            return res["data"].get("results", [])

        tasks = {"overdue": [], "due_soon": [], "backlog": [],
                 "blocked": [], "completed": 0}
        for page in fetch_all("task_db"):
            title = self._prop_value(page, "Task") or page.get("id")
            status = self._prop_value(page, "Status") or ""
            priority = self._prop_value(page, "Priority")
            category = self._prop_value(page, "Category")
            due = self._date_part(self._prop_value(page, "Due Date"))
            entry = {"id": page.get("id"), "title": title,
                     "status": status, "priority": priority,
                     "category": category, "due": due,
                     "url": page.get("url")}
            if status == "Completed":
                tasks["completed"] += 1
            elif status == "Blocked":
                tasks["blocked"].append(entry)
            elif due and due < today_s:
                tasks["overdue"].append(entry)
            elif due and due <= horizon:
                tasks["due_soon"].append(entry)
            else:
                tasks["backlog"].append(entry)

        calendar = []
        for page in fetch_all("content_calendar"):
            title = self._prop_value(page, "Title") or page.get("id")
            status = self._prop_value(page, "Status") or ""
            pub = self._date_part(self._prop_value(page, "Publish Date"))
            if pub and today_s <= pub <= horizon:
                calendar.append({
                    "id": page.get("id"), "title": title, "status": status,
                    "publish_date": pub, "url": page.get("url")})
            elif status in ("In Progress", "Review") and not pub:
                calendar.append({
                    "id": page.get("id"), "title": title, "status": status,
                    "publish_date": None, "url": page.get("url")})
        calendar.sort(key=lambda e: (e["publish_date"] or "9999"))

        return {"success": True, "action": "digest",
                "window_days": days, "today": today_s,
                "horizon": horizon,
                "tasks": tasks, "calendar": calendar}

    def _action_create_page(self, data: Dict[str, Any]) -> Dict[str, Any]:
        dbid = self._resolve_db(str(data.get("database") or ""))
        if not dbid:
            return {"success": False, "error": "Unknown database."}
        properties = data.get("properties")
        if not isinstance(properties, dict) or not properties:
            return {"success": False,
                    "error": "Missing 'properties' object for the new page."}
        payload = {"parent": {"database_id": dbid}, "properties": properties}
        if data.get("children"):
            payload["children"] = data["children"]
        res = self._request("POST", "/pages", payload)
        if not res.get("success"):
            return {**res, "action": "create_page"}
        page = res["data"]
        return {"success": True, "action": "create_page",
                "page": self._summarize_page(page)}

    def _action_update_page(self, data: Dict[str, Any]) -> Dict[str, Any]:
        page_id = str(data.get("page_id") or "").strip()
        properties = data.get("properties")
        if not page_id:
            return {"success": False, "error": "Missing page_id."}
        if not isinstance(properties, dict) or not properties:
            return {"success": False,
                    "error": "Missing 'properties' updates."}
        res = self._request("PATCH", f"/pages/{page_id}",
                            {"properties": properties})
        if not res.get("success"):
            return {**res, "action": "update_page"}
        return {"success": True, "action": "update_page",
                "page": self._summarize_page(res["data"])}

    def _action_archive_page(self, data: Dict[str, Any]) -> Dict[str, Any]:
        page_id = str(data.get("page_id") or "").strip()
        if not page_id:
            return {"success": False, "error": "Missing page_id."}
        res = self._request("PATCH", f"/pages/{page_id}", {"archived": True})
        if not res.get("success"):
            return {**res, "action": "archive_page"}
        return {"success": True, "action": "archive_page",
                "page": self._summarize_page(res["data"])}
