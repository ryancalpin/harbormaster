from __future__ import annotations
import asyncio
import sys
from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult


class TuiStubGateway(ApprovalGateway):
    """
    Stub gateway used when no TUI is connected.
    Prints to stderr and waits for stdin input (y/n).
    In production use, the real TUI gateway (Plan 2) replaces this.
    """

    def __init__(self, timeout: int = 0):
        self._timeout = timeout  # 0 = wait forever

    async def send_request(self, request: ApprovalRequest) -> None:
        print(
            f"\n[Harbormaster] Approval required:\n"
            f"  Action: {request.action}\n"
            f"  Port:   {request.port}\n"
            f"  Process: {request.process_name} (PID {request.pid})\n"
            f"  Requester: {request.requester}\n"
            f"Allow? [y/N]: ",
            end="",
            flush=True,
            file=sys.stderr,
        )

    async def wait_for_response(self, request: ApprovalRequest) -> ApprovalResult:
        loop = asyncio.get_event_loop()
        try:
            coro = loop.run_in_executor(None, input)
            if self._timeout > 0:
                answer = await asyncio.wait_for(coro, timeout=self._timeout)
            else:
                answer = await coro
        except asyncio.TimeoutError:
            print("\n[Harbormaster] Approval timed out — denying.", file=sys.stderr)
            return ApprovalResult.DENY
        except EOFError:
            return ApprovalResult.DENY
        return ApprovalResult.ALLOW if answer.strip().lower() == "y" else ApprovalResult.DENY

    async def cancel(self, request_id: str) -> None:
        pass  # nothing to cancel for stdin-based gateway
