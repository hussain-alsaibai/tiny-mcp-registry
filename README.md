# tiny-mcp-registry

> **Zero-dependency MCP server discovery and health checker. MIT.**

`tiny-mcp-registry` manages the lifecycle of Model Context Protocol (MCP) servers on your machine. It tracks which servers are installed, how to run them, and whether they are currently operational.

## Why?

As you install more MCP servers (GitHub, Slack, Google Drive, local tools), keeping track of their configurations and health becomes a chore. `tiny-mcp-registry` provides a single source of truth for your agentic toolset.

## Features

- **Persistent Registry:** Store server commands, args, and environment variables.
- **Health Checks:** Verify servers are responsive before starting a long agent run.
- **Zero Dependencies:** Pure Python, no external libraries required.
- **Agent-Ready:** Clean API for agents to discover their own capabilities.

## Install

```bash
pip install tiny-mcp-registry
```

## Quickstart

```python
from tiny_mcp_registry import TinyMCPRegistry

reg = TinyMCPRegistry()

# Register a new server
reg.register(
    name="github-mcp",
    command="npx",
    args=["@modelcontextprotocol/server-github"],
    env={"GITHUB_PERSONAL_ACCESS_TOKEN": "..."}
)

# Check health
if reg.check_health("github-mcp"):
    print("GitHub MCP is ready!")

# List all
for s in reg.list_servers():
    print(f"{s['name']}: {s['status']}")
```

## License

MIT
