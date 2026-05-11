import pytest
from harbormaster.web import build_ui_response


def test_secret_injected():
    html = build_ui_response("my-test-secret")
    assert 'const HM_SECRET = "my-test-secret"' in html


def test_required_dom_ids():
    html = build_ui_response("s")
    assert 'id="port-table"' in html
    assert 'id="approval-banner"' in html


def test_api_endpoints_referenced():
    html = build_ui_response("s")
    assert "/list" in html
    assert "/approvals" in html
    assert "/unlock" in html
    assert "/lock" in html
    assert "/evict" in html
    assert "/reserve/" in html


def test_placeholder_not_in_output():
    html = build_ui_response("real-secret")
    assert "__HM_SECRET__" not in html
