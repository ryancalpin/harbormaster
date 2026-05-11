import os
import pytest
import asyncio

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(autouse=True)
def clear_broken_ssl_cert_file(monkeypatch):
    """Remove SSL_CERT_FILE if it points to a non-existent file.

    Some environments set SSL_CERT_FILE to a path that doesn't exist, which
    causes httpx.Client() construction to fail with FileNotFoundError before
    any connection is attempted.
    """
    cert_file = os.environ.get("SSL_CERT_FILE")
    if cert_file and not os.path.exists(cert_file):
        monkeypatch.delenv("SSL_CERT_FILE")
