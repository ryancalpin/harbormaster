import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from harbormaster.tailscale import TailscaleDetector, TailscaleInfo

MOCK_STATUS = json.dumps({
    "Self": {
        "TailscaleIPs": ["100.64.0.1", "fd7a::1"],
        "HostName": "geo-hp-omen",
    }
})

async def test_detect_returns_info_when_available():
    detector = TailscaleDetector()
    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(MOCK_STATUS.encode(), b""))
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        info = await detector.detect()
    assert info is not None
    assert info.ipv4 == "100.64.0.1"
    assert info.hostname == "geo-hp-omen"

async def test_detect_returns_none_when_tailscale_missing():
    detector = TailscaleDetector()
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        info = await detector.detect()
    assert info is None

async def test_detect_returns_none_on_error_exit():
    detector = TailscaleDetector()
    proc = MagicMock()
    proc.returncode = 1
    proc.communicate = AsyncMock(return_value=(b"", b"not connected"))
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        info = await detector.detect()
    assert info is None

async def test_is_tailscale_interface():
    detector = TailscaleDetector()
    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(MOCK_STATUS.encode(), b""))
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        await detector.detect()
    assert detector.is_tailscale_ip("100.64.0.1")
    assert not detector.is_tailscale_ip("127.0.0.1")
