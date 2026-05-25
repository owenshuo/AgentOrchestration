"""API middleware components."""

import logging
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

REVOKED_TOKENS = {"revoked", "stale"}
PROTECTED_ROLES = {"admin", "owner"}


def _credential_value(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip()
    return request.cookies.get("dashboard_session", "").strip()


def _session_generation(request: Request) -> str:
    return request.headers.get("X-Session-Generation", "").strip()


def _token_generation(request: Request) -> str:
    return request.headers.get("X-Token-Generation", "").strip()


def _workspace_role(request: Request) -> str:
    return request.headers.get("X-Workspace-Role", "").strip().lower()


def _has_workspace_context(request: Request) -> bool:
    return bool(request.headers.get("X-Workspace-ID", "").strip())


def _auth_failure(request: Request) -> str:
    token = _credential_value(request)
    if not token:
        return "anonymous principal denied"
    if token.lower() in REVOKED_TOKENS:
        return "revoked or stale credential denied"
    session_generation = _session_generation(request)
    token_generation = _token_generation(request)
    if not session_generation or not token_generation:
        return "session rotation binding required"
    if session_generation != token_generation:
        return "refresh token is not bound to current session rotation"
    if not _has_workspace_context(request):
        return "workspace context required"
    if _workspace_role(request) not in PROTECTED_ROLES:
        return "insufficient workspace role"
    return ""


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        protected_api = (
            request.url.path.startswith("/api/v2")
            and request.url.path != "/api/v2/auth/token"
        )
        if protected_api:
            failure = _auth_failure(request)
            if failure:
                logger.info("dashboard auth rejected: %s", failure)
                status_code = 401
                if failure in {
                    "workspace context required",
                    "insufficient workspace role",
                }:
                    status_code = 403
                return Response(status_code=status_code, content=failure)
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._requests = {}

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        if client_ip not in self._requests:
            self._requests[client_ip] = []

        self._requests[client_ip] = [
            t for t in self._requests[client_ip]
            if now - t < self.window
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            return Response(status_code=429, content="Too many requests")

        self._requests[client_ip].append(now)
        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(
            "%s %s %s %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response
