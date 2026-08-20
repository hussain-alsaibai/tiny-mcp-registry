import os
import json
import time
import subprocess
import socket
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

@dataclass
class MCPServer:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    status: str = "unknown"
    last_check: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

class TinyMCPRegistry:
    """Zero-dependency MCP server discovery and health checker."""
    
    def __init__(self, config_path: str = "~/.mcp/registry.json"):
        self.config_path = os.path.expanduser(config_path)
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        self.servers: Dict[str, MCPServer] = self._load()

    def _load(self) -> Dict[str, MCPServer]:
        if not os.path.exists(self.config_path):
            return {}
        try:
            with open(self.config_path, 'r') as f:
                data = json.load(f)
                return {k: MCPServer(**v) for k, v in data.items()}
        except:
            return {}

    def save(self):
        with open(self.config_path, 'w') as f:
            json.dump({k: self._as_dict(s) for k, s in self.servers.items()}, f, indent=2)

    def _as_dict(self, s: MCPServer) -> Dict:
        d = vars(s).copy()
        return d

    def register(self, name: str, command: str, args: Optional[List[str]] = None, env: Optional[Dict] = None):
        self.servers[name] = MCPServer(name=name, command=command, args=args or [], env=env or {})
        self.save()

    def check_health(self, name: str) -> bool:
        if name not in self.servers: return False
        s = self.servers[name]
        try:
            # Simple check: can we start it? (non-destructive)
            # In a real MCP, we'd send a JSON-RPC 'initialize' request
            proc = subprocess.Popen(
                [s.command] + s.args,
                env={**os.environ, **s.env},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(0.5)
            if proc.poll() is None:
                s.status = "healthy"
                proc.terminate()
            else:
                s.status = "failed"
        except:
            s.status = "error"
        
        s.last_check = time.time()
        self.save()
        return s.status == "healthy"

    def list_servers(self) -> List[Dict]:
        return [self._as_dict(s) for s in self.servers.values()]

    def discover_local(self):
        """Placeholder for scanning common paths (e.g. node_modules/.bin/mcp-*)"""
        pass
