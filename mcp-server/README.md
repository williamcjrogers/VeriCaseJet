# Azad MCP Server for VeriCase

A comprehensive Model Context Protocol (MCP) server that exposes VeriCase forensic evidence analysis capabilities to AI coding agents.

## Features

### Tool Categories

| Category | Tools | Description |
|----------|-------|-------------|
| **Documents** | 10 tools | File management, uploads, versions, metadata |
| **Cases** | 12 tools | Construction dispute case management, claims, issues |
| **AI Orchestration** | 10 tools | Multi-model analysis, semantic search, claim narratives |
| **Search** | 9 tools | Full-text search across emails, documents, attachments |
| **Timeline** | 10 tools | Chronology management, delay analysis, critical path |
| **PST Processing** | 10 tools | Email archive processing, extraction, integrity |
| **Evidence** | 10 tools | Evidence linking, chains, bundles, suggestions |

**Total: 71 tools**

## Installation

```bash
cd mcp-server
pip install -e .
```

## Configuration

1. Copy `.env.example` to `.env`
2. Configure your VeriCase API credentials
3. Adjust feature flags as needed

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `VERICASE_API_URL` | VeriCase API endpoint | `http://localhost:8010` |
| `VERICASE_JWT_TOKEN` | JWT authentication token | - |
| `VERICASE_API_KEY` | Alternative API key auth | - |
| `ENABLE_AI_TOOLS` | Enable AI orchestration tools | `true` |
| `ENABLE_PST_TOOLS` | Enable PST processing tools | `true` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Usage

### Running the Server

```bash
# Direct execution
python -m src.server

# Or via installed script
azad-mcp
```

### Claude Desktop Configuration

Add to your Claude Desktop config (`~/.config/claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "azad-vericase": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/mcp-server",
      "env": {
        "VERICASE_API_URL": "http://localhost:8010",
        "VERICASE_JWT_TOKEN": "your_token"
      }
    }
  }
}
```

### VS Code / Cursor Configuration

Add to `.vscode/mcp.json`:

```json
{
  "mcpServers": {
    "azad-vericase": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "${workspaceFolder}/mcp-server"
    }
  }
}
```

## Prompts

The server includes pre-built prompts for common workflows:

| Prompt | Description |
|--------|-------------|
| `analyze_case` | Comprehensive case analysis with strategic recommendations |
| `search_evidence` | Search for evidence related to a topic |
| `draft_claim` | Draft a claim narrative |
| `analyze_timeline` | Analyze project timeline for delays |

## Resources

Access VeriCase data via resource URIs:

- `vericase://health` - API health status
- `vericase://cases/{case_id}` - Case details
- `vericase://documents/{document_id}` - Document details

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/
ruff check src/
```

## Architecture

```
mcp-server/
├── src/
│   ├── __init__.py
│   ├── server.py          # Main MCP server
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── documents.py   # Document management
│   │   ├── cases.py       # Case management
│   │   ├── ai_orchestrator.py  # AI tools
│   │   ├── search.py      # Search tools
│   │   ├── timeline.py    # Timeline/chronology
│   │   ├── pst.py         # PST processing
│   │   └── evidence.py    # Evidence linking
│   └── utils/
│       ├── __init__.py
│       ├── config.py      # Configuration
│       └── api_client.py  # HTTP client
├── pyproject.toml
├── mcp.json
└── README.md
```
