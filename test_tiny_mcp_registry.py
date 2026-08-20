import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
import tempfile
from tiny_mcp_registry import TinyMCPRegistry

def test_register_and_persist():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "registry.json")
        reg = TinyMCPRegistry(config_path=path)
        reg.register("gh", "npx", ["@modelcontextprotocol/server-github"], {"TOKEN": "x"})
        # Reload from disk
        reg2 = TinyMCPRegistry(config_path=path)
        assert "gh" in reg2.servers
        assert reg2.servers["gh"].command == "npx"
        assert reg2.servers["gh"].env == {"TOKEN": "x"}

def test_list_servers():
    reg = TinyMCPRegistry(config_path="/tmp/mcp-test-list.json")
    if os.path.exists("/tmp/mcp-test-list.json"):
        os.remove("/tmp/mcp-test-list.json")
    reg.register("a", "cmd1")
    reg.register("b", "cmd2")
    servers = reg.list_servers()
    assert len(servers) == 2
    os.remove("/tmp/mcp-test-list.json")

def test_health_unknown_command():
    reg = TinyMCPRegistry(config_path="/tmp/mcp-test-health.json")
    if os.path.exists("/tmp/mcp-test-health.json"):
        os.remove("/tmp/mcp-test-health.json")
    reg.register("nonexistent", "definitely-not-a-real-binary-xyz")
    ok = reg.check_health("nonexistent")
    assert ok is False
    os.remove("/tmp/mcp-test-health.json")

if __name__ == "__main__":
    test_register_and_persist()
    test_list_servers()
    test_health_unknown_command()
    print("tiny-mcp-registry: all tests passed")
