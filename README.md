# rellio-notion-api

Slim read-only Notion API backing the Soul Registry Studio's `/api/notion/*`
proxy. Extracted from `tiapmaatzu-rell-io/api_server.py` so the hosted
frontend can reach the canonical Notion databases without shipping the
integration token to the browser.

## Endpoints

| Route | Action |
|---|---|
| `GET /health`, `GET /api/health` | liveness |
| `GET /api/notion/status` | token config + bot identity |
| `GET /api/notion/sources` | canonical source registry |
| `GET /api/notion/databases` | live DB status |
| `GET /api/notion/databases/{db}/schema` | property schema + select options |
| `POST /api/notion/query` | filtered/paginated query |
| `GET /api/notion/pages/{id}` | single page properties |
| `GET /api/notion/search?q=` | workspace search |
| `GET /api/notion/digest?days=` | overdue tasks + upcoming calendar |

Write actions are intentionally not exposed — Notion mutations stay behind
the orchestrator's `confirmed=true` gate in the main API.

## Auth

`X-API-Token` header must match one of the comma-separated
`ALLOWED_API_TOKENS` env values. If unset, the API is open (same behavior
as the main service — always set it in production).

## Env vars

- `NOTION_TOKEN` — Notion integration token (server-side only)
- `ALLOWED_API_TOKENS` — comma-separated accepted `X-API-Token` values
- `PYTHON_VERSION` — `3.12.10` (Render default 3.14 breaks pydantic-core wheels)

## Deploy

Render free web service, auto-deploys from `main`:
`https://rellio-notion-api.onrender.com`

Note: Render free tier sleeps after ~15 min idle — first request after
idle is a cold start (~30–60s).
