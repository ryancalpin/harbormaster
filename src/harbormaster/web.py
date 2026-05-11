from __future__ import annotations
import importlib.resources


def build_ui_response(secret: str) -> str:
    """Read static/index.html, inject the daemon secret, return completed HTML."""
    html = (
        importlib.resources.files("harbormaster")
        .joinpath("static/index.html")
        .read_text(encoding="utf-8")
    )
    return html.replace('__HM_SECRET__', secret)
