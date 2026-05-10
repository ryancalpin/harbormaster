from __future__ import annotations
import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

from harbormaster.api import build_app
from harbormaster.approval.tui_stub import TuiStubGateway
from harbormaster.config import load_config, _default_db_path
from harbormaster.lock_engine import LockEngine
from harbormaster.negotiation import NegotiationHolds
from harbormaster.scanner import PortScanner
from harbormaster.state import StateDB
from harbormaster.tailscale import TailscaleDetector
from harbormaster.watcher import ProcessWatcher

logger = logging.getLogger("harbormaster")


class HarbormasterDaemon:
    def __init__(self, config_path: Path | None = None, db_path: Path | None = None):
        self.cfg = load_config(config_path)
        self._db_path = db_path or _default_db_path()
        self.db = StateDB(self._db_path)
        self.lock_engine = LockEngine()
        self.holds = NegotiationHolds()
        self.gateway = TuiStubGateway(timeout=self.cfg.approval_timeout)
        self.scanner = PortScanner(self.db, watch_range=tuple(self.cfg.watch_range))
        self.watcher = ProcessWatcher(self.db)
        self.tailscale = TailscaleDetector()
        self._scan_task: asyncio.Task | None = None

    async def startup(self) -> None:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr)
        logger.info("Harbormaster starting up")

        await self.db.init()
        await self.db.expire_reservations()

        api_port = self.cfg.api_port
        success = await self.lock_engine.lock(api_port)
        if not success:
            logger.error(f"Cannot bind to API port {api_port} — already in use. Is another instance running?")
            sys.exit(1)
        logger.info(f"API port :{api_port} locked")

        locked_records = await self.db.get_locked_ports()
        for record in locked_records:
            if record.port == api_port:
                continue
            ok = await self.lock_engine.lock(record.port)
            if not ok:
                logger.warning(f"Could not re-acquire lock on :{record.port} — port is in use")

        ts = await self.tailscale.detect()
        if ts:
            logger.info(f"Tailscale detected: {ts.ipv4} ({ts.hostname})")
        else:
            logger.info("Tailscale not available")

        live = await self.scanner.scan()
        await self.scanner.reconcile(live)

        logger.info(f"Startup complete — {len(locked_records)} lock(s) restored")

    async def _background_loop(self) -> None:
        tailscale_tick = 0
        while True:
            await asyncio.sleep(2)
            try:
                live = await self.scanner.scan()
                await self.scanner.reconcile(live)
                await self.watcher.check_all()
                self.holds.expire_stale()
                tailscale_tick += 1
                if tailscale_tick >= 15:  # every ~30s
                    tailscale_tick = 0
                    await self.tailscale.detect()
            except Exception as e:
                logger.exception(f"Background loop error: {e}")

    async def shutdown(self) -> None:
        logger.info("Harbormaster shutting down")
        if self._scan_task:
            self._scan_task.cancel()
        await self.lock_engine.shutdown()
        await self.db.close()

    async def serve(self) -> None:
        await self.startup()
        app = build_app(
            cfg=self.cfg,
            db=self.db,
            lock_engine=self.lock_engine,
            holds=self.holds,
            gateway=self.gateway,
        )
        self._scan_task = asyncio.create_task(self._background_loop())
        # Release the socket lock on the API port so uvicorn can bind it.
        await self.lock_engine.unlock(self.cfg.api_port)
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self.cfg.api_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        try:
            await server.serve()
        finally:
            await self.shutdown()


def install_service() -> None:
    """Copy systemd unit file and enable the user service."""
    import shutil
    import subprocess

    unit_src = Path(__file__).parent.parent.parent / "systemd" / "harbormaster.service"
    systemd_user_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_user_dir.mkdir(parents=True, exist_ok=True)
    dest = systemd_user_dir / "harbormaster.service"
    shutil.copy(unit_src, dest)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "harbormaster"], check=True)
    print("Harbormaster service installed and started.")
    print("  Status: systemctl --user status harbormaster")
    print("  Logs:   journalctl --user -u harbormaster -f")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        install_service()
        return
    daemon = HarbormasterDaemon()
    try:
        asyncio.run(daemon.serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
