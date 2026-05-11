import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta
from harbormaster.notification.event import NotificationEvent
from harbormaster.notification.expiry_notifier import ExpiryNotifier
from harbormaster.models import PortRecord, PortState


def test_notification_event_fields():
    event = NotificationEvent(
        event_type="reservation_expiring",
        port=3001,
        detail="expires in 30 minutes",
    )
    assert event.event_type == "reservation_expiring"
    assert event.port == 3001
    assert event.detail == "expires in 30 minutes"


@pytest.mark.asyncio
async def test_notifies_when_expiry_within_lead_time():
    db = AsyncMock()
    gateway = AsyncMock()
    soon = datetime.now(timezone.utc) + timedelta(minutes=30)
    record = PortRecord(port=3001, state=PortState.RESERVED, reserved_until=soon)
    db.list_ports.return_value = [record]

    notifier = ExpiryNotifier(lead_time_seconds=3600)
    await notifier.check(db, gateway)

    gateway.notify.assert_called_once()
    event = gateway.notify.call_args[0][0]
    assert event.event_type == "reservation_expiring"
    assert event.port == 3001


@pytest.mark.asyncio
async def test_does_not_notify_beyond_lead_time():
    db = AsyncMock()
    gateway = AsyncMock()
    far = datetime.now(timezone.utc) + timedelta(hours=5)
    record = PortRecord(port=3001, state=PortState.RESERVED, reserved_until=far)
    db.list_ports.return_value = [record]

    notifier = ExpiryNotifier(lead_time_seconds=3600)
    await notifier.check(db, gateway)

    gateway.notify.assert_not_called()


@pytest.mark.asyncio
async def test_does_not_notify_twice_for_same_port():
    db = AsyncMock()
    gateway = AsyncMock()
    soon = datetime.now(timezone.utc) + timedelta(minutes=30)
    record = PortRecord(port=3001, state=PortState.RESERVED, reserved_until=soon)
    db.list_ports.return_value = [record]

    notifier = ExpiryNotifier(lead_time_seconds=3600)
    await notifier.check(db, gateway)
    await notifier.check(db, gateway)

    gateway.notify.assert_called_once()


@pytest.mark.asyncio
async def test_skips_permanent_reservations():
    db = AsyncMock()
    gateway = AsyncMock()
    record = PortRecord(port=3001, state=PortState.RESERVED, reserved_until=None)
    db.list_ports.return_value = [record]

    notifier = ExpiryNotifier(lead_time_seconds=3600)
    await notifier.check(db, gateway)

    gateway.notify.assert_not_called()


@pytest.mark.asyncio
async def test_clears_notified_set_when_reservation_gone():
    db = AsyncMock()
    gateway = AsyncMock()
    soon = datetime.now(timezone.utc) + timedelta(minutes=30)
    record = PortRecord(port=3001, state=PortState.RESERVED, reserved_until=soon)
    db.list_ports.return_value = [record]

    notifier = ExpiryNotifier(lead_time_seconds=3600)
    await notifier.check(db, gateway)
    assert gateway.notify.call_count == 1

    # Reservation is gone (expired or unreserved)
    db.list_ports.return_value = []
    await notifier.check(db, gateway)

    # Port 3001 no longer in _notified, so if it comes back it would notify again
    assert 3001 not in notifier._notified
