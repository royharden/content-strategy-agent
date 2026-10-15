import pytest

from content_strategy.api.security import COOKIE_NAME, SessionGuard
from content_strategy.shared.grounded.audit import GateError

ORIGIN = "http://127.0.0.1:23456"  # Pure header fixture; no listener/reservation.


def headers(guard):
    cookie, csrf = guard.bootstrap([("host", "127.0.0.1:23456")])
    return [
        ("host", "127.0.0.1:23456"),
        ("origin", ORIGIN),
        ("cookie", cookie.split(";", 1)[0]),
        ("x-csrf-token", csrf),
        ("content-type", "application/json"),
        ("sec-fetch-site", "same-origin"),
    ]


def test_same_session_allowed_other_session_and_duplicate_cookies_refused():
    guard = SessionGuard(ORIGIN)
    values = headers(guard)
    guard.check(values, mutation=True)
    guard.check([pair for pair in values if pair[0] != "origin"], mutation=False)
    with pytest.raises(GateError, match="session_required"):
        SessionGuard(ORIGIN).check(values, mutation=True)
    duplicate = [(k, v + "; " + v if k == "cookie" else v) for k, v in values]
    with pytest.raises(GateError, match="ambiguous_cookie"):
        guard.check(duplicate, mutation=True)
    cookie, _ = guard.bootstrap([("host", guard.host)])
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie


@pytest.mark.parametrize(
    "key,value,code",
    [
        ("host", "evil.test:23456", "host_not_allowed"),
        ("host", "127.0.0.1:23457", "host_not_allowed"),
        ("origin", "http://evil.test", "origin_not_allowed"),
        ("origin", "null", "origin_not_allowed"),
        ("sec-fetch-site", "cross-site", "site_not_allowed"),
        ("content-type", "text/plain", "json_required"),
        ("content-type", "application/x-www-form-urlencoded", "json_required"),
        ("x-csrf-token", "wrong", "csrf_required"),
        ("x-csrf-token", "\u00e9", "csrf_required"),
        ("cookie", COOKIE_NAME + "=wrong", "session_required"),
        ("cookie", COOKIE_NAME + "=\u00e9", "session_required"),
        ("cookie", "malformed", "ambiguous_cookie"),
    ],
)
def test_mutation_closed_header_boundaries(key, value, code):
    guard = SessionGuard(ORIGIN)
    values = [(k, value if k == key else v) for k, v in headers(guard)]
    with pytest.raises(GateError, match=code):
        guard.check(values, mutation=True)


@pytest.mark.parametrize("key", ["origin", "cookie", "x-csrf-token", "content-type"])
def test_mutation_missing_and_duplicate_headers_refused(key):
    guard = SessionGuard(ORIGIN)
    values = headers(guard)
    with pytest.raises(GateError):
        guard.check([pair for pair in values if pair[0] != key], mutation=True)
    with pytest.raises(GateError, match="ambiguous_headers"):
        guard.check(values + [next(pair for pair in values if pair[0] == key)], mutation=True)


@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1:23456",
        "http://evil.test:23456",
        "http://127.0.0.1",
        "http://user@127.0.0.1:23456",
        ORIGIN + "/",
        ORIGIN + "?q=secret",
    ],
)
def test_guard_requires_explicit_loopback_config(origin):
    with pytest.raises(GateError, match="explicit_loopback_origin_required"):
        SessionGuard(origin)


def test_bootstrap_cannot_cross_site_or_rebind_host():
    guard = SessionGuard(ORIGIN)
    for values in [
        [("host", "evil.test:23456")],
        [("host", guard.host), ("origin", "http://evil.test")],
        [("host", guard.host), ("sec-fetch-site", "cross-site")],
        [("host", guard.host), ("origin", ORIGIN + "\r\n")],
    ]:
        with pytest.raises(GateError):
            guard.bootstrap(values)
