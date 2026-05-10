from harbormaster.models import PortState, PortRecord, LivePort
from datetime import datetime, timezone

def test_port_state_values():
    assert PortState.OPEN.value == "open"
    assert PortState.RESERVED.value == "reserved"
    assert PortState.IN_USE.value == "in-use"
    assert PortState.CLAIMED.value == "claimed"
    assert PortState.LOCKED.value == "locked"

def test_port_record_defaults():
    record = PortRecord(port=3000, state=PortState.OPEN)
    assert record.port == 3000
    assert record.pid is None
    assert record.process_name is None
    assert record.reserved_until is None

def test_live_port_fields():
    lp = LivePort(port=3000, pid=1234, process_name="node", is_listen=True, interface="127.0.0.1")
    assert lp.port == 3000
    assert lp.is_listen is True
