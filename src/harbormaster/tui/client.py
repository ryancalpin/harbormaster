from __future__ import annotations
import httpx
from harbormaster.config import HarbormasterConfig, load_config


class DaemonClient:
    """Async HTTP client for the harbormasterd API. Used by the TUI."""

    def __init__(self, cfg: HarbormasterConfig | None = None, transport=None) -> None:
        if cfg is None:
            cfg = load_config()
        self._base = f"http://127.0.0.1:{cfg.api_port}"
        self._headers = {"X-Harbormaster-Secret": cfg.secret}
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base,
                headers=self._headers,
                timeout=5,
                transport=self._transport,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> DaemonClient:
        await self._ensure_client()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    async def _get(self, path: str, **kwargs) -> dict:
        client = await self._ensure_client()
        r = await client.get(path, **kwargs)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, **kwargs) -> dict:
        client = await self._ensure_client()
        r = await client.post(path, **kwargs)
        r.raise_for_status()
        return r.json()

    async def health(self) -> dict:
        return await self._get("/health")

    async def list_ports(self) -> list[dict]:
        data = await self._get("/list")
        return data["ports"]

    async def live_ports(self) -> dict:
        return await self._get("/ports/live")

    async def list_approvals(self) -> list[dict]:
        data = await self._get("/approvals")
        return data["approvals"]

    async def respond_approval(self, request_id: str, result: str) -> dict:
        return await self._post(f"/approvals/{request_id}/respond", json={"result": result})

    async def lock(self, port: int) -> dict:
        return await self._post("/lock", json={"port": port})

    async def unlock(self, port: int) -> dict:
        return await self._post("/unlock", json={"port": port})

    async def evict(self, port: int) -> dict:
        return await self._post("/evict", json={"port": port})
