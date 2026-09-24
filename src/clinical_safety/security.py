"""API security primitives: auth, rate limiting, security headers.

All behavior is environment-gated so the local demo runs with zero config,
while any networked deployment can harden itself without code changes:

- ``HARNESS_API_KEY`` — when set, every ``/api/*`` route except ``/api/health``
  requires the ``X-API-Key`` header.
- ``HARNESS_RATE_LIMIT`` — max requests per IP per 60s window (default 120).
  Returns 429 when exceeded.
- Security headers are always applied (nosniff, DENY framing, referrer
  policy, a baseline CSP for the demo UI).
"""
from __future__ import annotations

import os
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def api_key_configured() -> str:
    return os.environ.get("HARNESS_API_KEY", "")


def rate_limit_max() -> int:
    return _env_int("HARNESS_RATE_LIMIT", 120)


_RATE_WINDOW_S = 60
_hits: dict[str, list[float]] = defaultdict(list)


def reset_rate_limiter() -> None:
    """Test hook: clear all recorded request timestamps."""
    _hits.clear()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> bool:
    """True if the request is within budget; records the hit."""
    now = time.monotonic()
    ip = _client_ip(request)
    window_start = now - _RATE_WINDOW_S
    recent = [t for t in _hits[ip] if t > window_start]
    _hits[ip] = recent
    if len(recent) >= rate_limit_max():
        return False
    recent.append(now)
    return True


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:"
    ),
}


async def security_middleware(request: Request, call_next):
    """Auth + rate-limit /api/* (except /api/health), then apply headers."""
    denied = authorize_request(request)
    if denied is not None:
        for k, v in SECURITY_HEADERS.items():
            denied.headers[k] = v
        return denied
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers[k] = v
    return response


def authorize_request(request: Request) -> JSONResponse | None:
    """Return an error response if the request fails auth/rate checks."""
    path = request.url.path
    if not path.startswith("/api/"):
        return None
    if path == "/api/health":
        return None
    if not check_rate_limit(request):
        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
    expected = api_key_configured()
    if expected and request.headers.get("x-api-key") != expected:
        return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
    return None
