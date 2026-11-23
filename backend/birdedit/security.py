"""Local-only request protection.

* The server binds to 127.0.0.1 (see __main__).
* Host header must be localhost/127.0.0.1 on our port (blocks DNS rebinding).
* Every /api request needs the per-launch secret token, sent as the
  ``X-BirdEdit-Token`` header (or ``t`` query parameter for <img> URLs).
  The token is only embedded in the page served from this origin, which other
  websites cannot read (no CORS headers are ever sent).
* A present Origin header must be this app's own origin.
"""

from __future__ import annotations

import hmac
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

OPEN_PATHS = {"/api/health"}


class LocalGuard(BaseHTTPMiddleware):
    def __init__(self, app, port: int, token: str, extra_origins: tuple[str, ...] = ()):
        super().__init__(app)
        self.port = port
        self.token = token
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", *extra_origins}
        self.extra_hosts = {o.split("//", 1)[1] for o in extra_origins}

    async def dispatch(self, request: Request, call_next):
        host = (request.headers.get("host") or "").lower()
        if host not in self.hosts and host not in self.extra_hosts:
            return JSONResponse({"detail": "Forbidden host"}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and origin not in self.origins:
            return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
        path = request.url.path
        if path.startswith("/api/") and path not in OPEN_PATHS:
            supplied = request.headers.get("x-birdedit-token") or request.query_params.get("t") or ""
            if not hmac.compare_digest(supplied.encode(), self.token.encode()):
                return JSONResponse({"detail": "Missing or invalid session token. Reload the page."},
                                    status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response


def new_token() -> str:
    return secrets.token_urlsafe(32)
