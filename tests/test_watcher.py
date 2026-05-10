import pytest
from unittest.mock import AsyncMock, patch
from harbormaster.models import PortState, PortRecord
from harbormaster.watcher import ProcessWatcher

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.list_ports = AsyncMock(return_value=[])
    db.remove_port = AsyncMock()
    db.set_port = AsyncMock()
    return db

async def test_dead_process_removes_record(mock_db):
    record = PortRecord(port=3000, state=PortState.CLAIMED, pid=9999, process_name="node")
    mock_db.list_ports.return_value = [record]
    watcher = ProcessWatcher(mock_db)
    with patch("psutil.pid_exists", return_value=False):
        await watcher.check_all()
    mock_db.remove_port.assert_called_once_with(3000)

async def test_live_process_unchanged(mock_db):
    record = PortRecord(port=3000, state=PortState.CLAIMED, pid=1234, process_name="node")
    mock_db.list_ports.return_value = [record]
    watcher = ProcessWatcher(mock_db)
    mock_proc = type("P", (), {"name": lambda self: "node"})()
    with patch("psutil.pid_exists", return_value=True), \
         patch("psutil.Process", return_value=mock_proc):
        await watcher.check_all()
    mock_db.remove_port.assert_not_called()

async def test_pid_recycled_rereg(mock_db):
    """PID exists but process name changed — treat as recycled, re-register."""
    record = PortRecord(port=3000, state=PortState.CLAIMED, pid=1234, process_name="node")
    mock_db.list_ports.return_value = [record]
    watcher = ProcessWatcher(mock_db)
    mock_proc = type("P", (), {"name": lambda self: "python3"})()
    with patch("psutil.pid_exists", return_value=True), \
         patch("psutil.Process", return_value=mock_proc):
        await watcher.check_all()
    mock_db.set_port.assert_called_once()
    updated = mock_db.set_port.call_args[0][0]
    assert updated.process_name == "python3"

async def test_locked_port_not_removed_on_process_exit(mock_db):
    """Locked ports keep their record even if the process exits (daemon holds the socket)."""
    record = PortRecord(port=3000, state=PortState.LOCKED, pid=1234, process_name="node")
    mock_db.list_ports.return_value = [record]
    watcher = ProcessWatcher(mock_db)
    with patch("psutil.pid_exists", return_value=False):
        await watcher.check_all()
    mock_db.remove_port.assert_not_called()
