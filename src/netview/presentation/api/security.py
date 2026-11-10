"""Host check, header check and security headers, as one pure ASGI middleware."""

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

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
        await self.app(scope, receive, send_with_headers)

    @staticmethod
    async def _reject(send: Send, reason: str) -> None:
        body = json.dumps({"error": reason}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
