from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass


@dataclass
class TailscaleInfo:
    ipv4: str
    ipv6: str | None
    hostname: str


class TailscaleDetector:
    def __init__(self):
        self._current: TailscaleInfo | None = None
        self._known_ips: set[str] = set()

    async def detect(self) -> TailscaleInfo | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "tailscale", "status", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                self._current = None
                self._known_ips = set()
                return None
        except FileNotFoundError:
            self._current = None
            self._known_ips = set()
            return None

        try:
            data = json.loads(stdout)
            ips: list[str] = data.get("Self", {}).get("TailscaleIPs", [])
            hostname: str = data.get("Self", {}).get("HostName", "")
            ipv4 = next((ip for ip in ips if ":" not in ip), None)
            ipv6 = next((ip for ip in ips if ":" in ip), None)
            if ipv4 is None:
                self._current = None
                self._known_ips = set()
                return None
            self._current = TailscaleInfo(ipv4=ipv4, ipv6=ipv6, hostname=hostname)
            self._known_ips = set(ips)
            return self._current
        except (json.JSONDecodeError, KeyError):
            self._current = None
            self._known_ips = set()
            return None

    def is_tailscale_ip(self, ip: str) -> bool:
        return ip in self._known_ips

    @property
    def current(self) -> TailscaleInfo | None:
        return self._current
