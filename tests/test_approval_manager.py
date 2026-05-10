import pytest
import asyncio
from harbormaster.approval.manager import ApprovalManager
from harbormaster.approval.base import ApprovalRequest, ApprovalResult


@pytest.fixture
def manager():
    return ApprovalManager()


async def test_register_and_respond(manager):
    req = ApprovalRequest(action="lock", port=3000)
    future = manager.register(req)
    assert not future.done()
    assert len(manager.list_pending()) == 1
    result = manager.respond(req.request_id, ApprovalResult.ALLOW)
    assert result is True
    assert await future == ApprovalResult.ALLOW


async def test_respond_unknown_id_returns_false(manager):
    result = manager.respond("nonexistent-id", ApprovalResult.DENY)
    assert result is False


async def test_cancel_removes_pending(manager):
    req = ApprovalRequest(action="evict", port=4000)
    future = manager.register(req)
    manager.cancel(req.request_id)
    assert len(manager.list_pending()) == 0
    assert future.cancelled()


async def test_list_pending_returns_requests(manager):
    req1 = ApprovalRequest(action="lock", port=3000)
    req2 = ApprovalRequest(action="evict", port=4000)
    manager.register(req1)
    manager.register(req2)
    pending = manager.list_pending()
    assert len(pending) == 2
    ports = {r.port for r in pending}
    assert {3000, 4000} == ports


async def test_register_second_time_same_id_is_idempotent(manager):
    req = ApprovalRequest(action="lock", port=3000)
    f1 = manager.register(req)
    f2 = manager.register(req)
    assert f1 is f2
