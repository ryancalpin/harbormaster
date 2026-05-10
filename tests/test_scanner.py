import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from harbormaster.models import PortState, PortRecord, LivePort
from harbormaster.scanner import PortScanner

def _make_mock_conn(laddr_ip, laddr_port, pid, status):
    conn = MagicMock()
    conn.laddr.ip = laddr_ip
    conn.laddr.port = laddr_port
    conn.pid = pid
    conn.status = status
    return conn

def _make_mock_proc(pid, name):
    proc = MagicMock()
    proc.pid = pid
    proc.name.return_value = name
    return proc

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_port = AsyncMock(return_value=None)
    db.set_port = AsyncMock()
    db.list_ports = AsyncMock(return_value=[])
    return db

async def test_scan_returns_live_ports(mock_db):
    scanner = PortScanner(mock_db, watch_range=(1024, 49151))
    conn = _make_mock_conn("127.0.0.1", 3000, 1234, "LISTEN")
    proc = _make_mock_proc(1234, "node")
    with patch("psutil.net_connections", return_value=[conn]), \
         patch("psutil.Process", return_value=proc):
        ports = await scanner.scan()
    assert len(ports) == 1
    assert ports[0].port == 3000
    assert ports[0].process_name == "node"
    assert ports[0].is_listen is True

async def test_scan_excludes_out_of_range(mock_db):
    scanner = PortScanner(mock_db, watch_range=(3000, 4000))
    conn = _make_mock_conn("127.0.0.1", 80, 1, "LISTEN")
    proc = _make_mock_proc(1, "nginx")
    with patch("psutil.net_connections", return_value=[conn]), \
         patch("psutil.Process", return_value=proc):
        ports = await scanner.scan()
    assert len(ports) == 0

async def test_reconcile_auto_registers_in_use(mock_db):
    scanner = PortScanner(mock_db, watch_range=(1024, 49151))
    live = [LivePort(port=3000, pid=1234, process_name="node", is_listen=True, interface="127.0.0.1")]
    mock_db.get_port.return_value = None
    await scanner.reconcile(live)
    mock_db.set_port.assert_called_once()
    record = mock_db.set_port.call_args[0][0]
    assert record.port == 3000
    assert record.state == PortState.CLAIMED
    assert record.pid == 1234

async def test_reconcile_skips_already_registered(mock_db):
    scanner = PortScanner(mock_db, watch_range=(1024, 49151))
    live = [LivePort(port=3000, pid=1234, process_name="node", is_listen=True, interface="127.0.0.1")]
    mock_db.get_port.return_value = PortRecord(port=3000, state=PortState.LOCKED, pid=1234)
    await scanner.reconcile(live)
    mock_db.set_port.assert_not_called()
