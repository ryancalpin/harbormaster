import sys
import pytest
import json
import httpx
from unittest.mock import patch, MagicMock
from harbormaster.cli import build_client, parse_ttl, cmd_request, cmd_list, cmd_status, main

SECRET = "test-secret"
BASE = "http://127.0.0.1:19191"


def mock_transport(responses: dict):
    """Build an httpx mock transport from {(method, path): (status, json)} dict."""
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key not in responses:
            raise AssertionError(f"Unexpected request: {key}")
        status, body = responses[key]
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def test_parse_ttl_hours():
    assert parse_ttl("2h") == 7200

def test_parse_ttl_days():
    assert parse_ttl("1d") == 86400

def test_parse_ttl_minutes():
    assert parse_ttl("30m") == 1800

def test_parse_ttl_invalid():
    with pytest.raises(ValueError):
        parse_ttl("forever")

def test_cmd_request_prints_port(capsys):
    transport = mock_transport({
        ("GET", "/request"): (200, {"assigned": 3001, "preferred": 3000, "reason": None, "hold_expires_at": "2026-01-01T00:00:00Z"}),
    })
    client = httpx.Client(base_url=BASE, transport=transport)
    cmd_request(client, port=3000)
    captured = capsys.readouterr()
    assert captured.out.strip() == "3001"

def test_cmd_list_outputs_table(capsys):
    transport = mock_transport({
        ("GET", "/list"): (200, {"ports": [
            {"port": 3000, "state": "locked", "pid": 1234, "process_name": "node", "reserved_until": None},
        ]}),
    })
    client = httpx.Client(base_url=BASE, transport=transport)
    cmd_list(client, reserved_only=False, as_json=False)
    captured = capsys.readouterr()
    assert "3000" in captured.out
    assert "locked" in captured.out

def test_cmd_list_json(capsys):
    transport = mock_transport({
        ("GET", "/list"): (200, {"ports": [
            {"port": 3000, "state": "locked", "pid": 1234, "process_name": "node", "reserved_until": None},
        ]}),
    })
    client = httpx.Client(base_url=BASE, transport=transport)
    cmd_list(client, reserved_only=False, as_json=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data[0]["port"] == 3000

def test_cmd_status_ok(capsys):
    transport = mock_transport({
        ("GET", "/health"): (200, {"status": "ok", "locked": 2}),
    })
    client = httpx.Client(base_url=BASE, transport=transport)
    cmd_status(client)
    captured = capsys.readouterr()
    assert "ok" in captured.out


def test_daemon_down_shows_friendly_message(capsys):
    """When the daemon isn't running, all commands print a friendly message and exit 1."""
    def handler(request):
        raise httpx.ConnectError("connection refused")
    client = httpx.Client(base_url=BASE, transport=httpx.MockTransport(handler))
    with pytest.raises(SystemExit) as exc_info:
        cmd_list(client, reserved_only=False, as_json=False)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "daemon is not running" in captured.err
    assert "harbormaster" in captured.err


def test_completion_bash(capsys, monkeypatch):
    """hm completion bash prints a non-empty bash completion script."""
    monkeypatch.setattr(sys, "argv", ["hm", "completion", "bash"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 100
    assert "complete" in captured.out


def test_completion_zsh(capsys, monkeypatch):
    """hm completion zsh prints a non-empty zsh completion script."""
    monkeypatch.setattr(sys, "argv", ["hm", "completion", "zsh"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 100
    assert "compdef" in captured.out or "#compdef" in captured.out


def test_completion_tcsh(capsys, monkeypatch):
    """hm completion tcsh prints a non-empty tcsh completion script."""
    monkeypatch.setattr(sys, "argv", ["hm", "completion", "tcsh"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 100
    assert "complete" in captured.out
