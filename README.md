# tiny-mcp-registry — MCP Server Discovery + Health Checks

> **MCP registry with runtime verification.**
> Not just "is the server up?" — but "does this tool actually work?"
> Zero dependencies. MIT. ~450 lines.

```bash
pip install tiny-mcp-registry
# or just copy tiny_mcp_registry/mcp_registry.py
```

## Why Runtime Verification?

Traditional MCP discovery: read the schema, hope it works.
New pattern: **probe the server** before suggesting it to an agent.

```python
# Old way
servers = mcp_registry.search("github", tool="create_pr")
# Returns servers that might be down, slow, or missing the tool

# New way
servers = mcp_registry.search("github", tool="create_pr",
    require_healthy=True,
    max_latency_ms=500,
    require_tool=True)
# Returns only servers that pass a live health check
```

## Quick Start

```python
from tiny_mcp_registry import create_default_registry, MCPRegistry

# Use built-in servers (GitHub, Slack, Postgres, etc.)
registry = create_default_registry()

# Register your own
registry.register("my-internal-api",
    url="https://api.internal.example.com/mcp",
    tools=["query_db", "get_config", "set_config"],
    categories=["internal", "database"])

# Search with filters
servers = registry.search(
    "github",
    tool="create_pr",
    require_healthy=True,
    max_latency_ms=500
)
for s in servers:
    print(f"{s.name}: {s.latency_ms:.0f}ms, {s.health_status}")

# Run health checks
registry.check_all()
```

## Built-in Servers

| Server | Protocol | Tools |
|--------|----------|-------|
| github | HTTP | create_issue, list_prs, add_comment |
| filesystem | stdio | read_file, write_file, list_directory |
| memory | stdio | create_memory, search_memory |
| slack | stdio | send_message, list_channels |
| postgres | stdio | query, list_tables, get_schema |
| sentry | stdio | list_issues, get_issue |
| google-maps | stdio | get_place, search_places, directions |

## Health Check Design

```python
class HealthChecker:
    # Latency thresholds
    HEALTHY:   < 500ms
    DEGRADED:  500ms - 2000ms
    UNHEALTHY: > 2000ms or connection failed
```

The checker tests:
1. **Reachability**: Can we connect to the server?
2. **Latency**: How long does it take?
3. **Schema**: Does it respond with valid MCP JSON?
4. **Tool presence**: Does the requested tool exist?

## CLI

```bash
# List all servers
python -m tiny_mcp_registry list

# Search with health filter
python -m tiny_mcp_registry search github --tool create_issue --healthy

# Run health checks
python -m tiny_mcp_registry check

# Show stats
python -m tiny_mcp_registry stats
```

## Search Filters

```python
registry.search(
    query="github",           # Text search in name, description, tools
    tool="create_pr",        # Must have tool matching this
    category="vcs",          # Must be in this category
    require_healthy=True,    # Skip unhealthy servers
    max_latency_ms=500,      # Skip slow servers
    require_tool=True,       # Tool name must match exactly
)
```

## Dependencies

**Zero.** Uses stdlib `urllib`, `socket`, `subprocess`.

## Benchmarks

| Operation | Latency | Notes |
|-----------|---------|-------|
| Registry search | **~0.1ms** | In-memory, no I/O |
| HTTP health check | **50-500ms** | Network-dependent |
| stdio health check | **100-1000ms** | Spawn + discovery |
| Check all (10 servers) | **~2s** | Sequential, ~200ms/server |

## License

MIT © 2026 Hussain Al-Saibai
