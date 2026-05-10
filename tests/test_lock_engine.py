import pytest
import socket
from harbormaster.lock_engine import LockEngine, PrivilegedPortError

@pytest.fixture
async def engine():
    e = LockEngine()
    yield e
    await e.shutdown()

def _get_ephemeral_port() -> int:
    """Find a free port by binding briefly to port 0."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

async def test_lock_free_port(engine):
    port = _get_ephemeral_port()
    result = await engine.lock(port)
    assert result is True
    assert engine.is_locked(port)

async def test_lock_already_locked_port_is_idempotent(engine):
    port = _get_ephemeral_port()
    await engine.lock(port)
    result = await engine.lock(port)
    assert result is True  # already held by us — idempotent

async def test_lock_in_use_port_fails(engine):
    # Hold a port externally, then try to lock it
    with socket.socket() as external:
        external.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        external.bind(("127.0.0.1", 0))
        port = external.getsockname()[1]
        result = await engine.lock(port)
    assert result is False

async def test_unlock_releases_port(engine):
    port = _get_ephemeral_port()
    await engine.lock(port)
    result = await engine.unlock(port)
    assert result is True
    assert not engine.is_locked(port)
    # Port should now be bindable by someone else
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))  # should not raise

async def test_unlock_non_locked_port(engine):
    result = await engine.unlock(9999)
    assert result is False

async def test_locked_ports_list(engine):
    p1 = _get_ephemeral_port()
    p2 = _get_ephemeral_port()
    await engine.lock(p1)
    await engine.lock(p2)
    locked = engine.locked_ports()
    assert p1 in locked
    assert p2 in locked

async def test_privileged_port_raises(engine):
    with pytest.raises(PrivilegedPortError):
        await engine.lock(80)

async def test_shutdown_releases_all(engine):
    port = _get_ephemeral_port()
    await engine.lock(port)
    await engine.shutdown()
    assert not engine.is_locked(port)
