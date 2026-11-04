"""Minimal JSON-RPC client for the BioBTree MCP server (stdlib only)."""

import json
import urllib.error
import urllib.request

import config


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, url=None, timeout=None):
        self.url = url or config.MCP_URL
        self.timeout = timeout or config.MCP_TIMEOUT
        self._id = 0
        self._tools = None

    # -- transport ---------------------------------------------------------
    def _post(self, payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "User-Agent": "biobtree-benchmark",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = r.read().decode("utf-8", "replace")
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise MCPError(f"HTTP {e.code}: {e.read()[:300]!r}") from e
        except Exception as e:  # noqa: BLE001
            raise MCPError(f"request failed: {e}") from e

        if "text/event-stream" in ctype:
            # SSE: take the last data: line that parses as JSON.
            for line in reversed(body.splitlines()):
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk:
                        return json.loads(chunk)
            raise MCPError("empty SSE response")

        return json.loads(body)

    def _rpc(self, method, params=None):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        resp = self._post(payload)
        if "error" in resp:
            raise MCPError(str(resp["error"]))
        return resp.get("result", {})

    # -- API ---------------------------------------------------------------
    def list_tools(self):
        """Raw MCP tool descriptors (cached)."""
        if self._tools is None:
            self._tools = self._rpc("tools/list").get("tools", [])
        return self._tools

    def openai_tools(self, names=None):
        """Tool descriptors in OpenAI function-calling format, optionally filtered."""
        out = []
        for t in self.list_tools():
            if names is not None and t["name"] not in names:
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                    },
                }
            )
        return out

    def call_tool(self, name, arguments):
        """Call a tool; return the text payload (MCP content blocks joined)."""
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        blocks = result.get("content", [])
        parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        if result.get("isError"):
            return "ERROR: " + "\n".join(parts)
        return "\n".join(parts)


if __name__ == "__main__":
    c = MCPClient()
    print(f"MCP: {c.url}")
    for t in c.list_tools():
        props = list(t.get("inputSchema", {}).get("properties", {}).keys())
        print(f"  {t['name']:<18} {props}")
    print("\nsearch SCN9A:")
    print(c.call_tool("biobtree_search", {"terms": "SCN9A", "dataset": "hgnc"})[:400])
