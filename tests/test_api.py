import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient
from harbormaster.api import build_app
from harbormaster.models import PortState, PortRecord
from harbormaster.config import HarbormasterConfig

SECRET = "test-secret-abc123"

@pytest.fixture
def cfg():
    c = HarbormasterConfig()
    c.secret = SECRET
    c.watch_range = (1024, 49151)
    return c

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.list_ports = AsyncMock(return_value=[])
    db.get_port = AsyncMock(return_value=None)
    db.set_port = AsyncMock()
    db.remove_port = AsyncMock()
    return db

@pytest.fixture
def mock_lock_engine():
    le = AsyncMock()
    le.lock = AsyncMock(return_value=True)
    le.unlock = AsyncMock(return_value=True)
    le.locked_ports = MagicMock(return_value=[])
    return le

@pytest.fixture
def mock_holds():
    h = MagicMock()
    h.is_held = MagicMock(return_value=False)
    h.next_available = MagicMock(return_value=3000)
    h.add = MagicMock()
    h.release = MagicMock()
    h.expire_stale = MagicMock()
    return h

@pytest.fixture
def mock_gateway():
    gw = AsyncMock()
    from harbormaster.approval.base import ApprovalResult
    gw.request_approval = AsyncMock(return_value=ApprovalResult.ALLOW)
    return gw

@pytest.fixture
def client(cfg, mock_db, mock_lock_engine, mock_holds, mock_gateway):
    app = build_app(cfg=cfg, db=mock_db, lock_engine=mock_lock_engine,
                    holds=mock_holds, gateway=mock_gateway)
    return TestClient(app, raise_server_exceptions=True)

def auth(secret=SECRET):
    return {"X-Harbormaster-Secret": secret}

def test_health(client):
    r = client.get("/health", headers=auth())
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_no_auth_returns_403(client):
    r = client.get("/health")
    assert r.status_code == 403

def test_wrong_secret_returns_403(client):
    r = client.get("/health", headers={"X-Harbormaster-Secret": "wrong"})
    assert r.status_code == 403

def test_request_port(client, mock_holds, mock_db):
    mock_db.list_ports.return_value = []
    r = client.get("/request?port=3000", headers=auth())
    assert r.status_code == 200
    data = r.json()
    assert "assigned" in data
    assert "hold_expires_at" in data

def test_request_port_no_available_returns_409(client, mock_holds):
    mock_holds.next_available.return_value = None
    r = client.get("/request?port=3000", headers=auth())
    assert r.status_code == 409

def test_lock_port(client):
    r = client.post("/lock", json={"port": 3001}, headers=auth())
    assert r.status_code == 200

def test_lock_port_failed_returns_409(client, mock_lock_engine):
    mock_lock_engine.lock.return_value = False
    r = client.post("/lock", json={"port": 3001}, headers=auth())
    assert r.status_code == 409

def test_unlock_port(client, mock_db):
    mock_db.get_port.return_value = PortRecord(port=3001, state=PortState.LOCKED)
    r = client.post("/unlock", json={"port": 3001}, headers=auth())
    assert r.status_code == 200

def test_claim_port(client):
    r = client.post("/claim", json={"port": 3001, "pid": 1234, "name": "node"}, headers=auth())
    assert r.status_code == 200

def test_list_ports(client, mock_db):
    mock_db.list_ports.return_value = [
        PortRecord(port=3000, state=PortState.LOCKED, pid=1234, process_name="node")
    ]
    r = client.get("/list", headers=auth())
    assert r.status_code == 200
    ports = r.json()["ports"]
    assert len(ports) == 1
    assert ports[0]["port"] == 3000
    assert ports[0]["state"] == "locked"
