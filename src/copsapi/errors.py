from __future__ import annotations

from typing import Optional

API_CODES = frozenset(
    {
        "missing_token",
        "invalid_token",
        "token_revoked",
        "insufficient_permissions",
        "rate_limited",
        "bad_request",
        "user_not_found",
        "game_not_found",
        "server_unavailable",
        "api_disabled",
        "internal_error",
    }
)

RETRYABLE = frozenset({"rate_limited", "server_unavailable", "api_disabled", "internal_error", "network", "timeout", "gateway"})


class CopsApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 0,
        retry_after: Optional[float] = None,
        *,
        method: Optional[str] = None,
        path: Optional[str] = None,
        local: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retry_after = retry_after
        self.method = method
        self.path = path
        self.local = local

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, status={self.status}, message={self.message!r})"


class AuthenticationError(CopsApiError):
    pass


class PermissionDeniedError(CopsApiError):
    pass


class RateLimitError(CopsApiError):
    pass


class BadRequestError(CopsApiError):
    pass


class NotFoundError(CopsApiError):
    pass


class ServiceUnavailableError(CopsApiError):
    pass


class ConnectionFailedError(CopsApiError):
    pass


class InvalidResponseError(CopsApiError):
    pass


class GameRejectedError(CopsApiError):
    pass


class GameGoneError(CopsApiError):
    pass


_CLASSES: dict[str, type[CopsApiError]] = {
    "missing_token": AuthenticationError,
    "invalid_token": AuthenticationError,
    "token_revoked": AuthenticationError,
    "insufficient_permissions": PermissionDeniedError,
    "rate_limited": RateLimitError,
    "bad_request": BadRequestError,
    "user_not_found": NotFoundError,
    "game_not_found": NotFoundError,
    "server_unavailable": ServiceUnavailableError,
    "api_disabled": ServiceUnavailableError,
    "internal_error": ServiceUnavailableError,
    "gateway": ServiceUnavailableError,
    "network": ConnectionFailedError,
    "timeout": ConnectionFailedError,
    "invalid_response": InvalidResponseError,
    "game_rejected": GameRejectedError,
    "game_gone": GameGoneError,
}


def make_error(
    code: str,
    message: str,
    status: int = 0,
    retry_after: Optional[float] = None,
    *,
    method: Optional[str] = None,
    path: Optional[str] = None,
    local: bool = False,
) -> CopsApiError:
    cls = _CLASSES.get(code, CopsApiError)
    return cls(code, message, status, retry_after, method=method, path=path, local=local)


def is_cops_error(err: object, *codes: str) -> bool:
    return isinstance(err, CopsApiError) and (not codes or err.code in codes)
