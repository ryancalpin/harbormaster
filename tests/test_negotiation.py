import pytest
from harbormaster.negotiation import NegotiationHolds

@pytest.fixture
def holds():
    return NegotiationHolds()

def test_add_and_check_hold(holds):
    holds.add(3000, ttl_seconds=10)
    assert holds.is_held(3000)

def test_release_hold(holds):
    holds.add(3000, ttl_seconds=10)
    holds.release(3000)
    assert not holds.is_held(3000)

def test_hold_expiry(holds):
    holds.add(3000, ttl_seconds=0)  # immediate expiry
    holds.expire_stale()
    assert not holds.is_held(3000)

def test_next_available_skips_held(holds):
    holds.add(3000, ttl_seconds=60)
    port = holds.next_available(3000, max_port=3010, unavailable={3001, 3002})
    assert port == 3003

def test_next_available_returns_none_when_exhausted(holds):
    result = holds.next_available(3000, max_port=3001, unavailable={3000, 3001})
    assert result is None

def test_next_available_returns_preferred_if_clear(holds):
    port = holds.next_available(3000, max_port=65000, unavailable=set())
    assert port == 3000

def test_double_add_resets_ttl(holds):
    holds.add(3000, ttl_seconds=60)
    holds.add(3000, ttl_seconds=60)  # should not raise, just refreshes
    assert holds.is_held(3000)
