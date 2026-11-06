"""HTTP hardening of the core (review IN-01), one pure ASGI middleware:

- Host check (DNS rebinding): the Host header must be an IP literal (the AP address 10.42.0.1,
  127.0.0.1...), a single-label name ("localhost", "jabuka") or an mDNS ".local" name. A public
  DNS name that an attacker re-points at the Pi is answered 421 (HTTP) or closed (WebSocket).
- Cross-site requests: POST/PUT/PATCH under /api/ need Content-Type application/json, which a
  cross-site <form> cannot send and a cross-site fetch cannot send without a CORS preflight the
  core never grants (415 otherwise). DELETE carries no form either way.
- Body size: request bodies over MAX_BODY_BYTES are refused (413) before they are buffered, so a
  single huge POST cannot fill the 1 GB Pi's RAM.
- Security headers on every HTTP response: Content-Security-Policy (same origin only; blob:
  workers for MapLibre, data:/blob: media for the NoSleep video), X-Frame-Options SAMEORIGIN (the
  helm app frames its own /diag.html), nosniff and no-referrer.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

MAX_BODY_BYTES = 64 * 1024
BODY_METHODS = {"POST", "PUT", "PATCH"}

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]

_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})$")


def split_host(host: str) -> tuple[str, str]:
    """(name, port) of a Host header: "[::1]:8000" -> ("::1", "8000"), "10.42.0.1" -> (.., "")."""
    host = host.strip()
    if host.startswith("["):
        end = host.find("]")
        if end < 0:
            return "", ""
        rest = host[end + 1 :]
        return host[1:end], rest[1:] if rest.startswith(":") else rest
    if host.count(":") == 1:
        name, port = host.split(":")
        return name, port
    return host, ""


def host_allowed(host: str | None) -> bool:
    if not host:
        return False
    name, port = split_host(host)
    if port and not (port.isdigit() and len(port) <= 5):
        return False
    name = name.rstrip(".").lower()
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    labels = name.split(".")
    if len(labels) == 1:
        return bool(_NAME.match(name))
    return labels[-1] == "local" and all(_NAME.match(lab) for lab in labels)


def csp(host: str) -> str:
    return "; ".join(
        (
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "media-src 'self' data: blob:",
            "worker-src 'self' blob:",
            "child-src 'self' blob:",
            f"connect-src 'self' ws://{host} wss://{host}",
            "frame-src 'self'",
            "frame-ancestors 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        )
    )


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k.lower() == name:
            return v.decode("latin-1")
    return None


async def _reply(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
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


class HardeningMiddleware:
    def __init__(self, app: App, max_body: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_body = max_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        host = _header(scope, b"host")
        if not host_allowed(host):
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await _reply(send, 421, "unknown host")
            return
        if kind == "websocket":
            await self.app(scope, receive, send)
            return
        assert host is not None
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        if method in BODY_METHODS and path.startswith("/api/"):
            ctype = (_header(scope, b"content-type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                await _reply(send, 415, "Content-Type must be application/json")
                return
        length = _header(scope, b"content-length")
        if length is not None:
            try:
                too_big = int(length) > self.max_body
            except ValueError:
                too_big = True
            if too_big:
                await _reply(send, 413, "request body too large")
                return
        if method in BODY_METHODS or (length is not None and length != "0"):
            body = bytearray()
            while True:
                msg = await receive()
                if msg["type"] != "http.request":
                    return  # client gone
                body += msg.get("body", b"")
                if len(body) > self.max_body:
                    await _reply(send, 413, "request body too large")
                    return
                if not msg.get("more_body", False):
                    break
            replayed = False

            async def replay() -> Message:
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            receive = replay

        policy = csp(host.strip())  # validated above: name or IP literal, optional digit port
        extra = [
            (b"content-security-policy", policy.encode("latin-1")),
            (b"x-frame-options", b"SAMEORIGIN"),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
        ]

        async def send_with_headers(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                names = {k.lower() for k, _ in msg.get("headers", [])}
                msg = dict(msg)
                msg["headers"] = list(msg.get("headers", [])) + [
                    (k, v) for k, v in extra if k not in names
                ]
            await send(msg)

        await self.app(scope, receive, send_with_headers)


def harden(app: Any) -> None:
    """Install the middleware on a FastAPI/Starlette app."""
    app.add_middleware(HardeningMiddleware)
