"""Pure loopback session checks. A host explicitly creates and retains one guard."""

import hmac
import secrets
from collections.abc import Iterable
from urllib.parse import urlsplit

from ..shared.grounded.audit import GateError

COOKIE_NAME = "s9_session"


class SessionGuard:
    def __init__(self, origin: str):
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is None
            or parsed.port == 0
            or parsed.path
            or parsed.query
            or parsed.fragment
            or origin != f"http://{parsed.netloc}"
        ):
            raise GateError("explicit_loopback_origin_required")
        self.origin, self.host = origin, parsed.netloc
        self._session = secrets.token_urlsafe(32)
        self._csrf = secrets.token_urlsafe(32)

    @staticmethod
    def _headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
        output = {}
        for key, value in headers:
            key = key.lower()
            if key in output or any(ord(c) < 32 or ord(c) == 127 for c in key + value):
                raise GateError("ambiguous_headers")
            output[key] = value
        return output

    def _site(self, headers: dict[str, str], *, bootstrap: bool):
        if headers.get("host") != self.host:
            raise GateError("host_not_allowed")
        if headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
            raise GateError("site_not_allowed")
        origin = headers.get("origin")
        if origin != self.origin and not (bootstrap and origin is None):
            raise GateError("origin_not_allowed")

    def bootstrap(self, headers: Iterable[tuple[str, str]]) -> tuple[str, str]:
        """Return Set-Cookie and CSRF values to a same-site host response only.

        The HTTP adapter must send no-store and must never log these values. Each
        guard is one ephemeral local session; no user identity is inferred from it.
        """
        values = self._headers(headers)
        self._site(values, bootstrap=True)
        return (
            f"{COOKIE_NAME}={self._session}; HttpOnly; SameSite=Strict; Path=/",
            self._csrf,
        )

    def check(self, headers: Iterable[tuple[str, str]], *, mutation: bool):
        values = self._headers(headers)
        self._site(values, bootstrap=not mutation)
        cookies = {}
        for part in values.get("cookie", "").split(";"):
            if not part.strip():
                continue
            name, equal, value = part.strip().partition("=")
            if not equal or name in cookies:
                raise GateError("ambiguous_cookie")
            cookies[name] = value
        if not hmac.compare_digest(
            cookies.get(COOKIE_NAME, "").encode("utf-8"), self._session.encode()
        ):
            raise GateError("session_required")
        if mutation:
            if values.get("content-type", "").lower() not in {
                "application/json",
                "application/json; charset=utf-8",
            }:
                raise GateError("json_required")
            if not hmac.compare_digest(
                values.get("x-csrf-token", "").encode("utf-8"), self._csrf.encode()
            ):
                raise GateError("csrf_required")
