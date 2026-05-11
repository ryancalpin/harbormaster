from __future__ import annotations
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

DAEMON_PORT = 19999
DAEMON_SECRET = "integration-test-secret"
DAEMON_BASE = f"http://127.0.0.1:{DAEMON_PORT}"


def _write_config(config_dir: Path, db_dir: Path) -> None:
    config_file = config_dir / "harbormaster" / "config.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        f"[daemon]\n"
        f"api_port = {DAEMON_PORT}\n"
        f'secret = "{DAEMON_SECRET}"\n'
        f"\n[approval]\n"
        f'gateway = "tui"\n'
    )
    (db_dir / "harbormaster").mkdir(parents=True)


@pytest.fixture(scope="session")
def daemon():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        config_dir = tmp / "config"
        db_dir = tmp / "data"
        _write_config(config_dir, db_dir)

        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(config_dir)
        env["XDG_DATA_HOME"] = str(db_dir)
        # Remove SSL_CERT_FILE if it points to a missing file to avoid httpx errors
        if "SSL_CERT_FILE" in env and not Path(env["SSL_CERT_FILE"]).exists():
            del env["SSL_CERT_FILE"]

        proc = subprocess.Popen(
            [sys.executable, "-m", "harbormaster.daemon"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Poll until healthy (5s timeout)
        deadline = time.monotonic() + 5
        healthy = False
        while time.monotonic() < deadline:
            try:
                with httpx.Client(verify=False) as poll_client:
                    r = poll_client.get(
                        f"{DAEMON_BASE}/health",
                        headers={"X-Harbormaster-Secret": DAEMON_SECRET},
                        timeout=0.5,
                    )
                if r.status_code == 200:
                    healthy = True
                    break
            except (httpx.ConnectError, httpx.RemoteProtocolError):
                pass
            time.sleep(0.1)

        if not healthy:
            stderr_out = b""
            try:
                proc.kill()
                _, stderr_out = proc.communicate(timeout=2)
            except Exception:
                pass
            raise RuntimeError(
                f"Daemon did not start within 5 seconds.\nDaemon stderr:\n{stderr_out.decode(errors='replace')}"
            )

        client = httpx.Client(
            base_url=DAEMON_BASE,
            headers={"X-Harbormaster-Secret": DAEMON_SECRET},
            timeout=10,
            verify=False,
        )

        yield client

        client.close()
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
