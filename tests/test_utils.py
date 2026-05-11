import pytest
from harbormaster.utils import parse_ttl


def test_parse_ttl_hours():
    assert parse_ttl("2h") == 7200


def test_parse_ttl_days():
    assert parse_ttl("1d") == 86400


def test_parse_ttl_minutes():
    assert parse_ttl("30m") == 1800


def test_parse_ttl_seconds():
    assert parse_ttl("90s") == 90


def test_parse_ttl_invalid():
    with pytest.raises(ValueError):
        parse_ttl("forever")


def test_parse_ttl_empty():
    with pytest.raises(ValueError):
        parse_ttl("")
