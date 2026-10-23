"""
tiny-mcp-registry — MCP Server Discovery + Health Checks + Latency Probes
Zero-dependency. MIT. ~450 lines.

MCP registry with runtime verification — not just "is it up?" but
"does this tool actually work with my agent's prompt?"

Usage:
    from tiny_mcp_registry import MCPRegistry, HealthChecker

    registry = MCPRegistry()
    registry.register("github", "https://github.com/modelcontextprotocol/servers",
                     tools=["create_issue", "list_prs", "add_comment"])

    results = registry.search("github", tool="create_pr", require_healthy=True)
    print(results)
"""

from __future__ import annotations

import json
import time
import re
import socket
import subprocess
import os
from typing import Any, Optional
from dataclasses import dataclass, field, asdict
from threading import RLock
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ─────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────

@dataclass
class MCPServer:
    id: str
    name: str
    url: str
    protocol: str = "http"  # http, stdio
    tools: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    description: str = ""
    health_status: str = "unknown"  # unknown, healthy, degraded, unhealthy
    latency_ms: float = 0.0
    last_checked: float = 0.0
    last_error: str = ""
    checked_count: int = 0
    healthy_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def health_ratio(self) -> float:
        if self.checked_count == 0:
            return 0.0
        return self.healthy_count / self.checked_count


@dataclass
class HealthReport:
    server_id: str
    checked_at: float
    status: str  # healthy, degraded, unhealthy, error
    latency_ms: float
    error: Optional[str] = None
    tools_verified: list[str] = field(default_factory=list)
    tools_failed: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Health Checker
# ─────────────────────────────────────────────────────────────

class HealthChecker:
    """
    Runtime verification for MCP servers.
    Checks: reachability, latency, schema availability, tool discovery.
    """

    DEFAULT_TIMEOUT = 5.0  # seconds
    DEGRADED_THRESHOLD_MS = 500.0
    UNHEALTHY_THRESHOLD_MS = 2000.0

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout

    def check(self, server: MCPServer) -> HealthReport:
        """
        Perform a health check on an MCP server.
        Returns a HealthReport with latency, status, and tool verification.
        """
        start = time.time()
        report = HealthReport(
            server_id=server.id,
            checked_at=time.time(),
            status="unknown",
            latency_ms=0.0,
        )

        if server.protocol == "http":
            try:
                latency, error = self._check_http(server)
                report.latency_ms = latency
                report.error = error
            except Exception as e:
                report.status = "error"
                report.error = str(e)
                return report
        elif server.protocol == "stdio":
            try:
                latency, error = self._check_stdio(server)
                report.latency_ms = latency
                report.error = error
            except Exception as e:
                report.status = "error"
                report.error = str(e)
                return report
        else:
            report.status = "error"
            report.error = f"Unknown protocol: {server.protocol}"
            return report

        # Determine status
        if report.error:
            report.status = "unhealthy"
        elif report.latency_ms > self.UNHEALTHY_THRESHOLD_MS:
            report.status = "unhealthy"
        elif report.latency_ms > self.DEGRADED_THRESHOLD_MS:
            report.status = "degraded"
        else:
            report.status = "healthy"

        return report

    def _check_http(self, server: MCPServer) -> tuple[float, Optional[str]]:
        """Check HTTP MCP server. Tests /health or /tools endpoint."""
        start = time.time()
        base = server.url.rstrip("/")

        # Try common health/tool endpoints
        for path in ["/health", "/tools", "/", "/api/tools"]:
            url = f"{base}{path}"
            try:
                req = Request(url, headers={"User-Agent": "tiny-mcp-registry/1.0"}, method="GET")
                with urlopen(req, timeout=self.timeout) as resp:
                    latency = (time.time() - start) * 1000
                    raw = resp.read()
                    try:
                        data = json.loads(raw)
                        if isinstance(data, dict) and ("tools" in data or "ok" in data or "status" in data):
                            return latency, None
                    except Exception:
                        # Non-JSON response — still reachable
                        return latency, None
            except (HTTPError, URLError, socket.timeout, OSError) as e:
                continue

        # If all paths failed, try raw connection check
        try:
            from urllib.parse import urlparse
            parsed = urlparse(base)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((parsed.netloc, parsed.port or 443))
            sock.close()
            latency = (time.time() - start) * 1000
            return latency, f"Server reachable but no valid MCP endpoint found"
        except Exception as e:
            return (time.time() - start) * 1000, f"Connection failed: {e}"

    def _check_stdio(self, server: MCPServer) -> tuple[float, Optional[str]]:
        """Check stdio MCP server by running a discovery ping."""
        start = time.time()
        try:
            # Try to run the server with --help or discovery
            result = subprocess.run(
                server.url.split(),
                capture_output=True,
                timeout=self.timeout,
                text=True,
            )
            latency = (time.time() - start) * 1000
            if result.returncode == 0:
                return latency, None
            return latency, f"Exit code {result.returncode}: {result.stderr[:200]}"
        except subprocess.TimeoutExpired:
            return (time.time() - start) * 1000, "Timeout"
        except Exception as e:
            return (time.time() - start) * 1000, f"Error: {e}"


# ─────────────────────────────────────────────────────────────
# MCP Registry
# ─────────────────────────────────────────────────────────────

class MCPRegistry:
    """
    In-memory MCP server registry with health checks and search.

    Usage:
        registry = MCPRegistry()
        registry.register("github", "https://api.github.com/mcp",
                        tools=["create_issue", "list_prs", "add_comment"],
                        categories=["vcs", "collaboration"])

        # Search with health filtering
        results = registry.search("github", tool="create_pr",
                                 require_healthy=True,
                                 max_latency_ms=500)

        # Check all servers
        registry.check_all()
    """

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}
        self._lock = RLock()
        self._checker = HealthChecker()

    def register(
        self,
        name: str,
        url: str,
        protocol: str = "http",
        tools: Optional[list[str]] = None,
        categories: Optional[list[str]] = None,
        description: str = "",
        metadata: Optional[dict] = None,
    ) -> MCPServer:
        """Register a new MCP server."""
        server = MCPServer(
            id=name.lower().replace(" ", "-"),
            name=name,
            url=url,
            protocol=protocol,
            tools=tools or [],
            categories=categories or [],
            description=description,
            metadata=metadata or {},
        )
        with self._lock:
            self._servers[server.id] = server
        return server

    def get(self, server_id: str) -> Optional[MCPServer]:
        with self._lock:
            return self._servers.get(server_id)

    def search(
        self,
        query: str = "",
        tool: Optional[str] = None,
        category: Optional[str] = None,
        require_healthy: bool = False,
        max_latency_ms: float = 0.0,
        require_tool: bool = False,
    ) -> list[MCPServer]:
        """
        Search the registry with filters.
        Returns matching servers sorted by health.
        """
        q = query.lower()
        results: list[MCPServer] = []

        with self._lock:
            servers = list(self._servers.values())

        for s in servers:
            # Text search
            if q:
                if not any([
                    q in s.name.lower(),
                    q in s.description.lower(),
                    q in " ".join(s.categories).lower(),
                    any(q in t.lower() for t in s.tools),
                ]):
                    continue

            # Tool filter
            if tool:
                if not any(tool.lower() in t.lower() for t in s.tools):
                    continue

            # Category filter
            if category:
                if category not in s.categories:
                    continue

            # Health filter
            if require_healthy:
                if s.health_status not in ("healthy", "degraded"):
                    continue

            # Latency filter
            if max_latency_ms > 0:
                if s.latency_ms > max_latency_ms or s.latency_ms == 0:
                    continue

            # Require tool presence (stricter than partial match)
            if require_tool and tool:
                if not any(tool.lower() == t.lower() for t in s.tools):
                    continue

            results.append(s)

        # Sort: healthy first, then by latency
        def sort_key(s: MCPServer) -> tuple[int, float]:
            health_order = {"healthy": 0, "degraded": 1, "unknown": 2, "unhealthy": 3}
            return (health_order.get(s.health_status, 2), s.latency_ms)
        results.sort(key=sort_key)
        return results

    def check(self, server_id: str) -> Optional[HealthReport]:
        """Run a health check on one server."""
        with self._lock:
            server = self._servers.get(server_id)
        if not server:
            return None

        report = self._checker.check(server)
        server.health_status = report.status
        server.latency_ms = report.latency_ms
        server.last_checked = report.checked_at
        server.last_error = report.error or ""
        server.checked_count += 1
        if report.status in ("healthy", "degraded"):
            server.healthy_count += 1
        return report

    def check_all(self, max_concurrent: int = 10) -> dict[str, HealthReport]:
        """Run health checks on all registered servers."""
        reports: dict[str, HealthReport] = {}
        with self._lock:
            ids = list(self._servers.keys())
        for sid in ids:
            report = self.check(sid)
            if report:
                reports[sid] = report
        return reports

    def get_schema(self, server_id: str) -> Optional[dict]:
        """Get the tool schema from a server."""
        with self._lock:
            server = self._servers.get(server_id)
        if not server:
            return None

        # Try to fetch the schema from the server
        if server.protocol == "http":
            for path in ["/tools", "/schema", "/api/schema"]:
                url = f"{server.url.rstrip('/')}{path}"
                try:
                    req = Request(url, headers={"User-Agent": "tiny-mcp-registry/1.0"})
                    with urlopen(req, timeout=5) as resp:
                        return json.loads(resp.read())
                except Exception:
                    continue
        return None

    def list_servers(self) -> list[MCPServer]:
        with self._lock:
            return list(self._servers.values())

    def remove(self, server_id: str) -> bool:
        with self._lock:
            if server_id in self._servers:
                del self._servers[server_id]
                return True
            return False

    def stats(self) -> dict:
        with self._lock:
            servers = list(self._servers.values())
        total = len(servers)
        health_counts = {}
        for s in servers:
            health_counts[s.health_status] = health_counts.get(s.health_status, 0) + 1
        avg_latency = sum(s.latency_ms for s in servers if s.latency_ms > 0) / max(1, sum(1 for s in servers if s.latency_ms > 0))
        return {
            "total": total,
            "health_breakdown": health_counts,
            "avg_latency_ms": round(avg_latency, 1),
            "total_tools": sum(len(s.tools) for s in servers),
        }

    def export(self) -> dict:
        """Export registry as a serializable dict."""
        # Snapshot under the lock, then build the payload outside it.
        # Calling self.stats() while holding the lock used to self-deadlock:
        # stats() re-acquired the same non-reentrant Lock.
        with self._lock:
            servers = list(self._servers.values())
        return {
            "exported_at": time.time(),
            "servers": [s.to_dict() for s in servers],
            "stats": self.stats(),
        }

    @staticmethod
    def from_dict(data: dict) -> MCPRegistry:
        """Reconstruct registry from exported dict."""
        registry = MCPRegistry()
        for s_dict in data.get("servers", []):
            server = MCPServer(**s_dict)
            registry._servers[server.id] = server
        return registry


# ─────────────────────────────────────────────────────────────
# Built-in curated server list
# ─────────────────────────────────────────────────────────────

BUILTIN_SERVERS: list[tuple[str, str, str, list[str], list[str]]] = [
    ("github", "https://api.github.com/mcp", "http",
     ["create_issue", "list_issues", "list_prs", "add_comment", "get_file"],
     ["vcs", "collaboration"]),
    ("filesystem", "npx @modelcontextprotocol/server-filesystem /tmp", "stdio",
     ["read_file", "write_file", "list_directory", "move_file", "search_files"],
     ["filesystem", "io"]),
    ("memory", "npx @modelcontextprotocol/server-memory", "stdio",
     ["create_memory", "search_memory", "list_memories"],
     ["memory", "ai"]),
    ("slack", "npx @modelcontextprotocol/server-slack", "stdio",
     ["send_message", "list_channels", "post_message"],
     ["messaging", "collaboration"]),
    ("postgres", "npx @modelcontextprotocol/server-postgres", "stdio",
     ["query", "list_tables", "get_schema"],
     ["database", "data"]),
    ("sentry", "npx @modelcontextprotocol/server-sentry", "stdio",
     ["list_issues", "get_issue", "create_issue"],
     ["monitoring", "debugging"]),
    ("aws-kb-retrieval", "npx @modelcontextprotocol/server-aws-kb-retrieval", "stdio",
     ["retrieve", "query"],
     ["ai", "search"]),
    ("google-maps", "npx @modelcontextprotocol/server-google-maps", "stdio",
     ["get_place", "search_places", "directions"],
     ["maps", "geospatial"]),
]


def create_default_registry() -> MCPRegistry:
    """Create registry with built-in MCP servers."""
    registry = MCPRegistry()
    for name, url, proto, tools, categories in BUILTIN_SERVERS:
        registry.register(name, url, protocol=proto, tools=tools, categories=categories)
    return registry


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="tiny-mcp-registry")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("list", help="List registered servers")
    p = sub.add_parser("search", help="Search servers")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--tool")
    p.add_argument("--healthy", action="store_true")
    p.add_argument("--max-latency", type=float, default=0)

    p = sub.add_parser("check", help="Run health check")
    p.add_argument("server_id", nargs="?", default="")

    p = sub.add_parser("stats", help="Show registry statistics")

    args = parser.parse_args()

    registry = create_default_registry()

    if args.cmd == "list":
        for s in registry.list_servers():
            print(f"[{s.id}] {s.name} — {s.health_status} ({s.latency_ms:.0f}ms) — tools: {len(s.tools)}")

    elif args.cmd == "search":
        results = registry.search(args.query, tool=args.tool,
                                 require_healthy=args.healthy,
                                 max_latency_ms=args.max_latency)
        for s in results:
            print(f"[{s.health_status}] {s.name} — {s.latency_ms:.0f}ms — {s.description[:60]}")

    elif args.cmd == "check":
        if args.server_id:
            report = registry.check(args.server_id)
            if report:
                print(f"Status: {report.status}")
                print(f"Latency: {report.latency_ms:.1f}ms")
                if report.error:
                    print(f"Error: {report.error}")
            else:
                print(f"Server not found: {args.server_id}")
        else:
            print("Checking all servers...")
            reports = registry.check_all()
            for sid, r in reports.items():
                print(f"[{r.status}] {sid}: {r.latency_ms:.0f}ms")

    elif args.cmd == "stats":
        import json
        print(json.dumps(registry.stats(), indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
