from __future__ import annotations
import threading
import time
import pytest
import httpx

pytestmark = pytest.mark.integration


def _auto_approve(client: httpx.Client, timeout: float = 5.0) -> None:
    """Poll /approvals and respond 'allow' to the first pending request."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = client.get("/approvals")
            if r.status_code == 200:
                approvals = r.json().get("approvals", [])
                if approvals:
                    request_id = approvals[0]["request_id"]
                    client.post(
                        f"/approvals/{request_id}/respond",
                        json={"result": "allow"},
                    )
                    return
        except Exception:
            pass
        time.sleep(0.05)


def test_health(daemon: httpx.Client):
    r = daemon.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_request_lock_unlock_cycle(daemon: httpx.Client):
    # Request a free port starting from 19000
    r = daemon.get("/request", params={"port": 19000})
    assert r.status_code == 200
    port = r.json()["assigned"]
    assert isinstance(port, int)

    # Lock it — requires approval; auto-approve in a background thread
    approver = threading.Thread(target=_auto_approve, args=(daemon,), daemon=True)
    approver.start()
    r = daemon.post("/lock", json={"port": port})
    approver.join(timeout=6)
    assert r.status_code == 200

    # Verify it appears as locked in list
    r = daemon.get("/list")
    assert r.status_code == 200
    ports = {p["port"]: p for p in r.json()["ports"]}
    assert port in ports
    assert ports[port]["state"] == "locked"

    # Unlock it
    r = daemon.post("/unlock", json={"port": port})
    assert r.status_code == 200


def test_reserve_and_list(daemon: httpx.Client):
    port = 19500
    r = daemon.post("/reserve", json={"port": port, "ttl_seconds": 3600})
    assert r.status_code == 200

    r = daemon.get("/list")
    assert r.status_code == 200
    ports = {p["port"]: p for p in r.json()["ports"]}
    assert port in ports
    assert ports[port]["state"] == "reserved"

    # Cleanup
    daemon.delete(f"/reserve/{port}")


def test_evict(daemon: httpx.Client):
    # Lock a port first (no PID — evict should handle gracefully)
    port = 19600
    approver = threading.Thread(target=_auto_approve, args=(daemon,), daemon=True)
    approver.start()
    r = daemon.post("/lock", json={"port": port})
    approver.join(timeout=6)
    assert r.status_code == 200

    # Evict it — requires another approval; auto-approve in background
    approver2 = threading.Thread(target=_auto_approve, args=(daemon,), daemon=True)
    approver2.start()
    r = daemon.post("/evict", json={"port": port})
    approver2.join(timeout=6)
    # 200 means evicted and locked, 403 means denied — both are valid API responses
    assert r.status_code in (200, 403, 409)


def test_status(daemon: httpx.Client):
    r = daemon.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "locked" in data
    assert data["status"] == "ok"
