import pytest
import httpx
from harbormaster.tui.client import DaemonClient
from harbormaster.config import HarbormasterConfig

SECRET = "test-secret"


class AsyncMockTransport(httpx.AsyncBaseTransport):
    """Async test transport that dispatches requests via a handler function."""

    def __init__(self, handler):
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def make_client(responses: dict) -> DaemonClient:
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key not in responses:
            return httpx.Response(404, json={"error": "not found"})
        status, body = responses[key]
        return httpx.Response(status, json=body)
    cfg = HarbormasterConfig()
    cfg.secret = SECRET
    transport = AsyncMockTransport(handler)
    return DaemonClient(cfg, transport=transport)


async def test_health():
    client = make_client({("GET", "/health"): (200, {"status": "ok", "locked": 1})})
    data = await client.health()
    assert data["status"] == "ok"


async def test_list_ports():
    client = make_client({
        ("GET", "/list"): (200, {"ports": [{"port": 3000, "state": "locked", "pid": 1, "process_name": "node", "reserved_until": None}]}),
    })
    ports = await client.list_ports()
    assert len(ports) == 1
    assert ports[0]["port"] == 3000


async def test_live_ports():
    client = make_client({
        ("GET", "/ports/live"): (200, {"ports": [{"port": 3000, "pid": 1, "process_name": "node", "is_listen": True, "interface": "127.0.0.1", "state": "locked"}], "tailscale_ip": None}),
    })
    data = await client.live_ports()
    assert len(data["ports"]) == 1


async def test_list_approvals():
    client = make_client({
        ("GET", "/approvals"): (200, {"approvals": [{"request_id": "abc", "action": "lock", "port": 3000, "pid": None, "process_name": None, "requester": ""}]}),
    })
    approvals = await client.list_approvals()
    assert len(approvals) == 1
    assert approvals[0]["action"] == "lock"


async def test_respond_approval():
    client = make_client({
        ("POST", "/approvals/abc/respond"): (200, {"request_id": "abc", "result": "allow"}),
    })
    data = await client.respond_approval("abc", "allow")
    assert data["result"] == "allow"
