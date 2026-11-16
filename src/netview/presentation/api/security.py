"""Host check, header check and security headers, as one pure ASGI middleware."""

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from netview.domain.dashboard import MAX_BYTES as LAYOUT_MAX_BYTES

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)
SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
]
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Routes whose request body is capped, checked before any JSON is parsed: (method, path) -> bytes.
BODY_LIMITS = {
    ("PUT", "/api/v1/dashboard/layout"): LAYOUT_MAX_BYTES,
    ("PUT", "/api/v1/admin/dashboard/default"): LAYOUT_MAX_BYTES,
}


def host_name(header: str) -> str:
    """The host part of a Host header, lower-case, without the port; IPv6 keeps its brackets."""
    value = header.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[: end + 1] if end != -1 else value
    if value.count(":") == 1:
        return value.partition(":")[0]
    return value


def normalize_allowed(hosts: set[str]) -> set[str]:
    """Allowed names as configured; a bare IPv6 address such as ``::1`` gets its brackets."""
    return {f"[{h}]" if ":" in h and not h.startswith("[") else h.lower() for h in hosts}


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: set[str]) -> None:
        self.app = app
        self.allowed = normalize_allowed(allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                names = {name for name, _ in SECURITY_HEADERS}
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in names]
                message = {**message, "headers": [*kept, *SECURITY_HEADERS]}
            await send(message)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if host_name(headers.get("host", "")) not in self.allowed:
            await self._reject(send_with_headers, "host not allowed")
            return
        if scope["method"] not in SAFE_METHODS and headers.get("x-netview") != "1":
            await self._reject(send_with_headers, "missing X-Netview header")
            return
        limit = BODY_LIMITS.get((scope["method"], scope["path"]))
        if limit is not None:
            replay = await self._capped(headers, receive, send_with_headers, limit)
            if replay is None:
                return
            receive = replay
        await self.app(scope, receive, send_with_headers)

    async def _capped(
        self, headers: dict[str, str], receive: Receive, send: Send, limit: int
    ) -> Receive | None:
        """Read the body, at most ``limit`` bytes of it, and hand it on again; None once a 413 was sent."""
        too_big = f"the request body is larger than {limit // 1024} KB"
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            await self._reject(send, too_big, 413)
            return None
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break  # the client went away
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > limit:
                await self._reject(send, too_big, 413)
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        replay = [{"type": "http.request", "body": b"".join(chunks), "more_body": False}]

        async def replayed() -> Message:
            return replay.pop() if replay else await receive()

        return replayed

    @staticmethod
    async def _reject(send: Send, reason: str, status: int = 403) -> None:
        body = json.dumps({"error": reason}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
