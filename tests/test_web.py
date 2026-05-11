import pytest
from unittest.mock import AsyncMock, MagicMock
from starlette.testclient import TestClient
from harbormaster.web import build_ui_response
from harbormaster.api import build_app
from harbormaster.config import HarbormasterConfig
from harbormaster.approval.tui_stub import TuiStubGateway


def test_secret_injected():
    html = build_ui_response("my-test-secret")
    assert 'const HM_SECRET = "my-test-secret"' in html


def test_required_dom_ids():
    html = build_ui_response("s")
    assert 'id="port-table"' in html
    assert 'id="approval-banner"' in html


def test_api_endpoints_referenced():
    html = build_ui_response("s")
    assert "/list" in html
    assert "/approvals" in html
    assert "/unlock" in html
    assert "/lock" in html
    assert "/evict" in html
    assert "/reserve/" in html


def test_placeholder_not_in_output():
    html = build_ui_response("real-secret")
    assert "__HM_SECRET__" not in html


SECRET = "web-test-secret"


@pytest.fixture
def web_client():
    cfg = HarbormasterConfig()
    cfg.secret = SECRET
    db = AsyncMock()
    db.list_ports = AsyncMock(return_value=[])
    lock_engine = MagicMock()
    lock_engine.locked_ports = MagicMock(return_value=set())
    holds = MagicMock()
    gateway = TuiStubGateway()
    app = build_app(cfg=cfg, db=db, lock_engine=lock_engine, holds=holds, gateway=gateway)
    return TestClient(app, raise_server_exceptions=False)


def test_ui_route_returns_html(web_client):
    r = web_client.get("/ui")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Harbormaster" in r.text
    assert SECRET in r.text


def test_ui_route_no_auth_required(web_client):
    """GET /ui must be accessible without the secret header."""
    r = web_client.get("/ui")  # no X-Harbormaster-Secret header
    assert r.status_code == 200
