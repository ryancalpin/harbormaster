from __future__ import annotations
import sys

import httpx
from mcp.server.fastmcp import FastMCP

from harbormaster.config import load_config

mcp = FastMCP("harbormaster", instructions=(
    "Harbormaster manages port allocation. Before starting any server, call "
    "request_port to get a free port. Call claim_port after binding. "
    "lock_port and evict_port require user approval."
))


def _client() -> httpx.Client:
    cfg = load_config()
    return httpx.Client(
        base_url=f"http://127.0.0.1:{cfg.api_port}",
        headers={"X-Harbormaster-Secret": cfg.secret},
        timeout=30,
    )


def _api(method: str, path: str, **kwargs) -> dict:
    with _client() as c:
        r = c.request(method, path, **kwargs)
        r.raise_for_status()
        return r.json()


@mcp.tool()
def request_port(port: int = 3000) -> str:
    """
    Request a free port to bind. Returns the assigned port number.
    Prefer calling this before starting any server or service.
    The returned port is held for 10 seconds — call claim_port after binding.
    """
    data = _api("GET", "/request", params={"port": port})
    assigned = data["assigned"]
    reason = data.get("reason")
    if reason:
        return f"{assigned}  (preferred {port} unavailable: {reason})"
    return str(assigned)


@mcp.tool()
def claim_port(port: int, pid: int | None = None, name: str = "unknown") -> str:
    """Register a port as in-use. Call this after binding the port returned by request_port."""
    _api("POST", "/claim", json={"port": port, "pid": pid, "name": name})
    return f"Port {port} claimed."


@mcp.tool()
def lock_port(port: int) -> str:
    """
    Lock a port so no other process can bind to it (requires user approval).
    The daemon holds a socket on the port — any intruder gets EADDRINUSE.
    """
    try:
        _api("POST", "/lock", json={"port": port})
        return f"Port {port} locked."
    except httpx.HTTPStatusError as e:
        return f"Error: {e.response.json().get('error', str(e))}"


@mcp.tool()
def unlock_port(port: int) -> str:
    """Release a lock on a port."""
    _api("POST", "/unlock", json={"port": port})
    return f"Port {port} unlocked."


@mcp.tool()
def evict_port(port: int) -> str:
    """
    Kill the process occupying a port, then lock it (requires user approval).
    Only use when you need a specific port that is currently occupied.
    """
    try:
        data = _api("POST", "/evict", json={"port": port})
        return f"Port {port} evicted (PID {data.get('evicted_pid')}) and locked."
    except httpx.HTTPStatusError as e:
        return f"Error: {e.response.json().get('error', str(e))}"


@mcp.tool()
def list_ports() -> str:
    """List all ports tracked by Harbormaster and their current states."""
    data = _api("GET", "/list")
    ports = data["ports"]
    if not ports:
        return "No ports registered."
    lines = [f"{'PORT':<8} {'STATE':<10} {'PROCESS':<16} PID"]
    for p in ports:
        lines.append(
            f":{p['port']:<7} {p['state']:<10} {p.get('process_name') or '':<16} {p.get('pid') or ''}"
        )
    return "\n".join(lines)


@mcp.tool()
def daemon_status() -> str:
    """Check if the Harbormaster daemon is running and get basic stats."""
    try:
        data = _api("GET", "/health")
        return f"Daemon: {data['status']} | Locked ports: {data['locked']}"
    except httpx.ConnectError:
        return "Daemon is not running. Start it with: harbormasterd"


def main() -> None:
    mcp.run(transport="stdio")
