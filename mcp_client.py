"""
mcp_client.py — Minimal JSON-RPC client for the AnySiteMCP server.

Calls tools on the local MCP server at http://localhost:4299/mcp.
Handles both plain JSON and SSE (text/event-stream) responses.
"""

import json
import requests

MCP_URL = "http://localhost:4299/mcp"
_req_id  = 0


def call_tool(name: str, arguments: dict = None) -> object:
    """
    Call an MCP tool and return the parsed result.

    Raises RuntimeError if the tool returns an error.
    """
    global _req_id
    _req_id += 1

    payload = {
        "jsonrpc": "2.0",
        "id": _req_id,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments or {},
        },
    }

    resp = requests.post(
        MCP_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        timeout=90,  # browser tools (SSO) can be slow
    )
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        data = _parse_sse(resp.text)
    else:
        data = resp.json()

    return _unwrap(data)


# ─────────────────────────────────────────────
#  Internals
# ─────────────────────────────────────────────

def _unwrap(data: dict) -> object:
    """Extract the result content from a JSON-RPC envelope."""
    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error'].get('message', data['error'])}")

    result = data.get("result", {})

    if result.get("isError"):
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        raise RuntimeError(" ".join(texts) or "Tool returned an error")

    for item in result.get("content", []):
        if item.get("type") == "text":
            text = item["text"]
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text

    return result


def _parse_sse(body: str) -> dict:
    """
    Parse a text/event-stream response and return the last JSON-RPC message.
    SSE lines look like:  data: {...}
    """
    last = None
    for line in body.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            try:
                last = json.loads(raw)
            except json.JSONDecodeError:
                pass
    if last is None:
        raise RuntimeError("No valid SSE data frame received from MCP server")
    return last
