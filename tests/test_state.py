import pytest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from harbormaster.models import PortState, PortRecord
from harbormaster.state import StateDB

@pytest.fixture
async def db(tmp_path):
    d = StateDB(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()

async def test_set_and_get_port(db):
    record = PortRecord(port=3000, state=PortState.LOCKED, pid=1234, process_name="node")
    await db.set_port(record)
    result = await db.get_port(3000)
    assert result is not None
    assert result.state == PortState.LOCKED
    assert result.pid == 1234
    assert result.process_name == "node"

async def test_get_missing_port_returns_none(db):
    result = await db.get_port(9999)
    assert result is None

async def test_remove_port(db):
    await db.set_port(PortRecord(port=3000, state=PortState.LOCKED))
    await db.remove_port(3000)
    assert await db.get_port(3000) is None

async def test_list_ports(db):
    await db.set_port(PortRecord(port=3000, state=PortState.LOCKED))
    await db.set_port(PortRecord(port=4000, state=PortState.CLAIMED, pid=5678))
    ports = await db.list_ports()
    assert len(ports) == 2
    port_numbers = {p.port for p in ports}
    assert {3000, 4000} == port_numbers

async def test_get_locked_ports(db):
    await db.set_port(PortRecord(port=3000, state=PortState.LOCKED))
    await db.set_port(PortRecord(port=4000, state=PortState.CLAIMED))
    locked = await db.get_locked_ports()
    assert len(locked) == 1
    assert locked[0].port == 3000

async def test_expire_reservations(db):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.set_port(PortRecord(port=3000, state=PortState.RESERVED, reserved_until=past))
    await db.set_port(PortRecord(port=4000, state=PortState.RESERVED, reserved_until=future))
    await db.expire_reservations()
    assert await db.get_port(3000) is None
    result = await db.get_port(4000)
    assert result is not None

async def test_upsert_updates_existing(db):
    await db.set_port(PortRecord(port=3000, state=PortState.CLAIMED, pid=100))
    await db.set_port(PortRecord(port=3000, state=PortState.LOCKED, pid=100))
    result = await db.get_port(3000)
    assert result.state == PortState.LOCKED
