"""API middleware components."""

import logging
import os
import time
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on", "production"}
_FALSE_VALUES = {"0", "false", "no", "off", "development", "test"}
_SECURITY_STATE_KEY = "ao_security_decision"


def _env_flag(*names: str, default: bool = False) -> bool:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    return default


class SecurityMiddleware(BaseHTTPMiddleware):
    """Fail closed on insecure proxy scheme before handlers run."""

    def __init__(self, app, require_https_proxy: Optional[bool] = None):
        super().__init__(app)
        self.require_https_proxy = (
            require_https_proxy
            if require_https_proxy is not None
            else _env_flag(
                "AO_REQUIRE_HTTPS_PROXY",
                "REQUIRE_HTTPS_PROXY",
                "AO_PRODUCTION_PROXY_MODE",
                "PRODUCTION_PROXY_MODE",
            )
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        request.state.ao_security_decision = "allowed"
        try:
            should_reject = (
                self.require_https_proxy
                and not _is_https_proxy_request(request)
            )
            if should_reject:
                request.state.ao_security_decision = "rejected"
                logger.warning(
                    "Rejected request with insecure proxy scheme",
                    extra={"path": request.url.path},
                )
                return Response(
                    status_code=400,
                    content="HTTPS required",
                    headers={"X-AO-Security-Decision": "rejected"},
                )

            response = await call_next(request)
            response.headers["X-AO-Security-Decision"] = "allowed"
            return response
        finally:
            _clear_security_state(request)


def _is_https_proxy_request(request: Request) -> bool:
    forwarded_proto = _get_forwarded_proto(request.headers.get("forwarded"))
    if forwarded_proto:
        return forwarded_proto == "https"

    forwarded_scheme = request.headers.get("x-forwarded-proto", "")
    if forwarded_scheme:
        first_scheme = forwarded_scheme.split(",", 1)[0].strip().lower()
        return first_scheme == "https"

    return request.url.scheme == "https"


def _get_forwarded_proto(header_value: Optional[str]) -> Optional[str]:
    if not header_value:
        return None

    first_entry = header_value.split(",", 1)[0]
    for part in first_entry.split(";"):
        key, _, value = part.strip().partition("=")
        if key.lower() == "proto":
            return value.strip('"').lower()
    return None


def _clear_security_state(request: Request) -> None:
    request.state._state.pop(_SECURITY_STATE_KEY, None)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        is_api_request = request.url.path.startswith("/api/v2")
        is_token_request = request.url.path == "/api/v2/auth/token"
        if is_api_request and not is_token_request:
            token = request.headers.get("Authorization", "")
            if not token.startswith("Bearer "):
                return Response(status_code=401, content="Unauthorized")
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
            t for t in self._requests[client_ip] if now - t < self.window
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
            f"{request.method} {request.url.path} "
            f"{response.status_code} {duration:.3f}s"
        )
        return response

# 2019-03-01T18:35:19 update

# 2019-04-03T13:22:05 update

# 2019-04-30T17:18:49 update

# 2019-08-20T09:29:03 update

# 2019-08-30T15:52:06 update

# 2019-11-23T16:58:42 update

# 2020-02-18T10:04:07 update

# 2020-04-21T17:35:30 update

# 2020-05-22T11:10:34 update

# 2020-07-02T12:31:26 update

# 2020-07-05T13:52:59 update

# 2020-08-21T20:36:45 update

# 2021-01-19T09:17:15 update

# 2021-01-29T11:34:24 update

# 2021-02-04T15:21:21 update

# 2021-04-19T19:23:15 update

# 2021-05-20T16:50:15 update

# 2021-06-22T19:23:44 update

# 2021-09-09T13:44:55 update

# 2021-09-16T09:30:20 update

# 2021-10-14T20:42:33 update

# 2021-12-28T16:39:14 update

# 2022-01-26T19:07:27 update

# 2022-01-28T08:03:41 update

# 2022-03-23T12:17:02 update

# 2022-04-06T12:12:27 update

# 2022-04-21T14:53:01 update

# 2022-06-30T08:37:32 update

# 2022-07-06T10:44:45 update

# 2022-11-02T11:12:47 update

# 2022-11-15T20:54:21 update

# 2022-11-23T14:13:34 update

# 2023-01-26T10:03:44 update

# 2023-02-09T17:08:10 update

# 2023-02-16T10:04:00 update

# 2023-03-14T11:52:03 update

# 2023-04-10T12:42:07 update

# 2023-04-26T10:43:39 update

# 2023-06-27T08:18:07 update

# 2023-08-30T15:30:40 update

# 2023-08-30T14:10:05 update

# 2023-10-09T18:32:46 update

# 2023-11-21T20:35:55 update

# 2024-03-07T19:17:39 update

# 2024-04-01T18:06:19 update

# 2024-07-18T15:37:34 update

# 2024-07-25T09:21:53 update

# 2024-08-12T14:24:22 update

# 2024-11-18T08:50:54 update

# 2025-04-08T12:43:05 update

# 2025-06-03T08:10:47 update

# 2025-06-12T08:37:52 update

# 2025-06-17T08:36:56 update

# 2025-07-02T18:09:42 update

# 2025-07-22T12:39:21 update

# 2025-10-13T12:13:46 update

# 2025-12-05T09:44:22 update

# 2025-12-22T18:34:47 update

# 2026-01-26T15:36:23 update

# 2026-02-13T12:36:40 update

# 2026-02-26T11:07:15 update

# 2026-03-19T11:00:17 update

# 2026-03-27T12:58:53 update

# 2026-05-12T17:19:36 update
