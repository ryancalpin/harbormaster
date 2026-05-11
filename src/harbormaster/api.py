from __future__ import annotations
import asyncio
import os
import psutil
import signal
from datetime import datetime, timedelta, timezone

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from harbormaster.web import build_ui_response

from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult
from harbormaster.approval.manager import ApprovalManager
from harbormaster.config import HarbormasterConfig
from harbormaster.lock_engine import LockEngine, PrivilegedPortError
from harbormaster.models import PortRecord, PortState
from harbormaster.negotiation import NegotiationHolds
from harbormaster.scanner import PortScanner
from harbormaster.state import StateDB
from harbormaster.tailscale import TailscaleDetector


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret: str):
        super().__init__(app)
        self._secret = secret

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/ui":
            return await call_next(request)
        if request.headers.get("X-Harbormaster-Secret") != self._secret:
            return JSONResponse({"error": "unauthorized"}, status_code=403)
        return await call_next(request)


def build_app(
    cfg: HarbormasterConfig,
    db: StateDB,
    lock_engine: LockEngine,
    holds: NegotiationHolds,
    gateway: ApprovalGateway,
    approval_manager: ApprovalManager | None = None,
    scanner: PortScanner | None = None,
    tailscale: TailscaleDetector | None = None,
) -> Starlette:

    async def ui(request: Request) -> Response:
        from starlette.responses import HTMLResponse
        return HTMLResponse(build_ui_response(cfg.secret))

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "locked": len(lock_engine.locked_ports()),
        })

    async def request_port(request: Request) -> JSONResponse:
        try:
            preferred = int(request.query_params.get("port", 3000))
            max_port = int(request.query_params.get("max_port", 65000))
        except ValueError:
            return JSONResponse({"error": "port and max_port must be integers"}, status_code=400)
        records = await db.list_ports()
        unavailable = {
            r.port for r in records
            if r.state in (PortState.LOCKED, PortState.RESERVED, PortState.CLAIMED)
        }
        holds.expire_stale()
        assigned = holds.next_available(preferred, max_port, unavailable)
        if assigned is None:
            return JSONResponse(
                {"error": f"No available port found in range {preferred}–{max_port}"},
                status_code=409,
            )
        holds.add(assigned, ttl_seconds=10)
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
        reason = None
        if assigned != preferred:
            blocking = next((r for r in records if r.port == preferred), None)
            if blocking:
                reason = f"{preferred} {blocking.state.value} by {blocking.process_name} PID {blocking.pid}"
        return JSONResponse({
            "assigned": assigned,
            "preferred": preferred,
            "reason": reason,
            "hold_expires_at": expiry,
        })

    async def lock_port(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            port = int(body["port"])
        except (Exception,):
            return JSONResponse({"error": "invalid request body"}, status_code=400)
        approval = ApprovalRequest(action="lock", port=port)
        result = await gateway.request_approval(approval)
        if result != ApprovalResult.ALLOW:
            return JSONResponse({"error": "denied"}, status_code=403)
        try:
            success = await lock_engine.lock(port)
        except PrivilegedPortError as e:
            return JSONResponse({"error": str(e)}, status_code=422)
        if not success:
            return JSONResponse({"error": f"Port {port} is in use and cannot be locked"}, status_code=409)
        existing = await db.get_port(port)
        record = PortRecord(
            port=port,
            state=PortState.LOCKED,
            pid=existing.pid if existing else None,
            process_name=existing.process_name if existing else None,
        )
        await db.set_port(record)
        return JSONResponse({"port": port, "state": "locked"})

    async def unlock_port(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            port = int(body["port"])
        except (Exception,):
            return JSONResponse({"error": "invalid request body"}, status_code=400)
        await lock_engine.unlock(port)
        await db.remove_port(port)
        return JSONResponse({"port": port, "state": "open"})

    async def evict_port(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            port = int(body["port"])
        except (Exception,):
            return JSONResponse({"error": "invalid request body"}, status_code=400)
        existing = await db.get_port(port)
        pid = existing.pid if existing else None
        process_name = existing.process_name if existing else None

        is_systemd = False
        if pid:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "systemctl", "status", str(pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(proc.communicate(), timeout=2.0)
                    is_systemd = proc.returncode == 0
                except asyncio.TimeoutError:
                    proc.kill()
            except FileNotFoundError:
                pass

        approval = ApprovalRequest(
            action="evict",
            port=port,
            pid=pid,
            process_name=process_name,
            requester="systemd-managed — may restart automatically." if is_systemd else "",
        )
        result = await gateway.request_approval(approval)
        if result != ApprovalResult.ALLOW:
            return JSONResponse({"error": "denied"}, status_code=403)

        if pid:
            try:
                if psutil.pid_exists(pid):
                    proc_obj = psutil.Process(pid)
                    if process_name is not None and proc_obj.name() != process_name:
                        # PID recycled to different process — abort kill
                        return JSONResponse({"error": "PID reuse detected — eviction aborted"}, status_code=409)
                    # When process_name is not stored we cannot validate — proceed
                    os.kill(pid, signal.SIGTERM)
                    await asyncio.sleep(3)
                    if psutil.pid_exists(pid):
                        os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        try:
            await lock_engine.lock(port)
        except PrivilegedPortError:
            pass
        record = PortRecord(port=port, state=PortState.LOCKED)
        await db.set_port(record)
        return JSONResponse({"port": port, "state": "locked", "evicted_pid": pid})

    async def claim_port(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            port = int(body["port"])
        except (Exception,):
            return JSONResponse({"error": "invalid request body"}, status_code=400)
        raw_pid = body.get("pid")
        try:
            pid = int(raw_pid) if raw_pid is not None else None
        except (ValueError, TypeError):
            return JSONResponse({"error": "pid must be an integer"}, status_code=400)
        name = body.get("name", "unknown")
        holds.release(port)
        record = PortRecord(port=port, state=PortState.CLAIMED, pid=pid, process_name=name)
        await db.set_port(record)
        return JSONResponse({"port": port, "state": "claimed"})

    async def reserve_port(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            port = int(body["port"])
        except (Exception,):
            return JSONResponse({"error": "invalid request body"}, status_code=400)
        ttl_seconds = body.get("ttl_seconds")
        if ttl_seconds is None:
            return JSONResponse({"error": "ttl_seconds required"}, status_code=422)
        reserved_until = (
            None if ttl_seconds == -1
            else datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        )
        record = PortRecord(port=port, state=PortState.RESERVED, reserved_until=reserved_until)
        await db.set_port(record)
        return JSONResponse({
            "port": port,
            "state": "reserved",
            "reserved_until": reserved_until.isoformat() if reserved_until else "permanent",
        })

    async def unreserve_port(request: Request) -> JSONResponse:
        port = int(request.path_params["port"])
        existing = await db.get_port(port)
        if existing is None or existing.state != PortState.RESERVED:
            return JSONResponse({"error": "Port is not reserved"}, status_code=404)
        await db.remove_port(port)
        return JSONResponse({"port": port, "state": "open"})

    async def list_ports(request: Request) -> JSONResponse:
        records = await db.list_ports()
        return JSONResponse({"ports": [r.to_dict() for r in records]})

    async def list_approvals(request: Request) -> JSONResponse:
        if approval_manager is None:
            return JSONResponse({"approvals": []})
        pending = approval_manager.list_pending()
        return JSONResponse({"approvals": [
            {
                "request_id": r.request_id,
                "action": r.action,
                "port": r.port,
                "pid": r.pid,
                "process_name": r.process_name,
                "requester": r.requester,
            }
            for r in pending
        ]})

    async def respond_approval(request: Request) -> JSONResponse:
        if approval_manager is None:
            return JSONResponse({"error": "no approval manager"}, status_code=503)
        request_id = request.path_params["request_id"]
        try:
            body = await request.json()
            result_str = body["result"]
        except (Exception,):
            return JSONResponse({"error": "invalid request body"}, status_code=400)
        from harbormaster.approval.base import ApprovalResult
        try:
            result = ApprovalResult(result_str)
        except ValueError:
            return JSONResponse({"error": "result must be 'allow' or 'deny'"}, status_code=400)
        ok = approval_manager.respond(request_id, result)
        if not ok:
            return JSONResponse({"error": "unknown request_id"}, status_code=404)
        return JSONResponse({"request_id": request_id, "result": result_str})

    async def live_ports(request: Request) -> JSONResponse:
        if scanner is None:
            return JSONResponse({"ports": [], "tailscale_ip": None})
        live = await scanner.scan()
        db_records = await db.list_ports()
        db_map = {r.port: r for r in db_records}
        ts_ip = tailscale.current.ipv4 if tailscale and tailscale.current else None
        result = []
        for lp in live:
            db_rec = db_map.get(lp.port)
            result.append({
                "port": lp.port,
                "pid": lp.pid,
                "process_name": lp.process_name,
                "is_listen": lp.is_listen,
                "interface": lp.interface,
                "state": db_rec.state.value if db_rec else "in-use",
            })
        return JSONResponse({"ports": result, "tailscale_ip": ts_ip})

    routes = [
        Route("/ui", ui),
        Route("/health", health),
        Route("/request", request_port),
        Route("/lock", lock_port, methods=["POST"]),
        Route("/unlock", unlock_port, methods=["POST"]),
        Route("/evict", evict_port, methods=["POST"]),
        Route("/claim", claim_port, methods=["POST"]),
        Route("/reserve", reserve_port, methods=["POST"]),
        Route("/reserve/{port:int}", unreserve_port, methods=["DELETE"]),
        Route("/list", list_ports),
        Route("/approvals", list_approvals),
        Route("/approvals/{request_id}/respond", respond_approval, methods=["POST"]),
        Route("/ports/live", live_ports),
    ]

    return Starlette(
        routes=routes,
        middleware=[Middleware(AuthMiddleware, secret=cfg.secret)],
    )
