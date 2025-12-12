# VeriCase MCP Server

A lightweight MCP server exposing a small, read-only tool surface over the VeriCase API.

## Config

- `VERICASE_API_BASE_URL` (default: `http://localhost:8010`)
- `VERICASE_API_TOKEN` (required)
- `VERICASE_API_TIMEOUT_S` (default: `30`)
- `VERICASE_API_MAX_RETRIES` (default: `3`)

## Run (stdio)

```pwsh
$env:VERICASE_API_BASE_URL = "http://localhost:8010"
$env:VERICASE_API_TOKEN = "<your bearer token>"
python -m api.app.mcp --transport stdio
```

## Run (SSE)

```pwsh
$env:VERICASE_API_BASE_URL = "http://localhost:8010"
$env:VERICASE_API_TOKEN = "<your bearer token>"
python -m api.app.mcp --transport sse --host 127.0.0.1 --port 8001
```
