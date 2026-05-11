import pytest
from harbormaster.notification.event import NotificationEvent


def test_notification_event_fields():
    event = NotificationEvent(
        event_type="reservation_expiring",
        port=3001,
        detail="expires in 30 minutes",
    )
    assert event.event_type == "reservation_expiring"
    assert event.port == 3001
    assert event.detail == "expires in 30 minutes"
