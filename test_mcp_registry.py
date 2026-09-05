"""Tests for tiny-mcp-registry."""
import pytest
from tiny_mcp_registry import (
    MCPRegistry, MCPServer, HealthChecker, create_default_registry
)


class TestMCPServer:
    def test_server_to_dict(self):
        s = MCPServer(
            id="test-server",
            name="Test Server",
            url="https://test.example.com/mcp",
            tools=["tool_a", "tool_b"],
        )
        d = s.to_dict()
        assert d["id"] == "test-server"
        assert "tool_a" in d["tools"]

    def test_health_ratio(self):
        s = MCPServer(
            id="test",
            name="Test",
            url="http://test.com",
            checked_count=10,
            healthy_count=7,
        )
        assert s.health_ratio == 0.7


class TestMCPRegistry:
    def test_register(self):
        r = MCPRegistry()
        s = r.register("github", "https://api.github.com/mcp",
                        tools=["create_issue", "list_prs"],
                        categories=["vcs"])
        assert s.id == "github"
        assert len(s.tools) == 2

    def test_get(self):
        r = MCPRegistry()
        r.register("test", "http://test.com")
        s = r.get("test")
        assert s is not None
        assert s.name == "test"
        assert r.get("nonexistent") is None

    def test_search_text(self):
        r = MCPRegistry()
        r.register("github", "https://api.github.com/mcp",
                   description="GitHub API integration",
                   tools=["create_issue"])
        r.register("slack", "https://api.slack.com/mcp",
                   description="Slack messaging",
                   tools=["send_message"])
        results = r.search("github")
        assert len(results) == 1
        assert results[0].id == "github"

    def test_search_tool_filter(self):
        r = MCPRegistry()
        r.register("s1", "http://s1.com", tools=["read", "write"])
        r.register("s2", "http://s2.com", tools=["read"])
        results = r.search(tool="write")
        assert len(results) == 1
        assert results[0].id == "s1"

    def test_search_healthy_filter(self):
        r = MCPRegistry()
        s1 = r.register("healthy", "http://h.com", tools=["x"])
        s1.health_status = "healthy"
        s2 = r.register("unhealthy", "http://u.com", tools=["x"])
        s2.health_status = "unhealthy"
        results = r.search(require_healthy=True)
        assert len(results) == 1
        assert results[0].id == "healthy"

    def test_search_latency_filter(self):
        r = MCPRegistry()
        s1 = r.register("fast", "http://f.com", tools=["x"])
        s1.latency_ms = 50.0
        s2 = r.register("slow", "http://s.com", tools=["x"])
        s2.latency_ms = 600.0
        results = r.search(max_latency_ms=500)
        assert len(results) == 1
        assert results[0].id == "fast"

    def test_remove(self):
        r = MCPRegistry()
        r.register("test", "http://t.com")
        assert r.remove("test") is True
        assert r.get("test") is None
        assert r.remove("nonexistent") is False

    def test_stats(self):
        r = MCPRegistry()
        s = r.register("x", "http://x.com", tools=["a", "b"])
        s.health_status = "healthy"
        s.latency_ms = 100
        stats = r.stats()
        assert stats["total"] == 1
        assert stats["total_tools"] == 2

    def test_export_reconstruct(self):
        r = MCPRegistry()
        r.register("test", "http://t.com", tools=["x", "y"])
        data = r.export()
        assert len(data["servers"]) == 1
        r2 = MCPRegistry.from_dict(data)
        assert r2.get("test").tools == ["x", "y"]


class TestCreateDefaultRegistry:
    def test_creates_servers(self):
        r = create_default_registry()
        servers = r.list_servers()
        assert len(servers) >= 5
        names = {s.id for s in servers}
        assert "github" in names
        assert "filesystem" in names


class TestHealthChecker:
    def test_check_http_invalid(self):
        h = HealthChecker(timeout=1.0)
        s = MCPServer(
            id="invalid",
            name="Invalid",
            url="http://127.0.0.1:9/mcp",  # nothing listening
            protocol="http",
        )
        report = h.check(s)
        assert report.status == "error" or report.status == "unhealthy"
        assert report.latency_ms > 0
