"""Owned ASGI route controls, without an event loop, socket, listener or browser."""

import base64
import json
import socket

import pytest

from content_strategy.api.http import create_app
from content_strategy.api.security import SessionGuard
from content_strategy.api.service import Selection
from content_strategy.runtime.local import local_host

ORIGIN = "http://127.0.0.1:29999"  # ASGI scope only; no port is opened or reserved.


class Direct:
    def __init__(self, tmp_path):
        self.host = local_host(tmp_path / "review.sqlite3", tmp_path / "calls.sqlite3", "http-test")
        self.app = create_app(self.host, SessionGuard(ORIGIN))
        self.headers = {"host": "127.0.0.1:29999"}
        session, response = self.request("/api/session", method="GET")
        self.headers.update(
            {
                "cookie": response["set-cookie"].split(";", 1)[0],
                "x-csrf-token": session["csrf"],
                "origin": ORIGIN,
                "content-type": "application/json",
            }
        )

    def request(self, path, value=None, *, method="POST", headers=None, status=200):
        payload = json.dumps(value).encode() if value is not None else b""
        sent, received = [], False

        async def receive():
            nonlocal received
            assert not received, "unexpected additional ASGI receive"
            received = True
            return {"type": "http.request", "body": payload, "more_body": False}

        async def send(message):
            sent.append(message)

        coroutine = self.app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (k.encode(), v.encode())
                    for k, v in (self.headers if headers is None else headers).items()
                ],
                "server": ("127.0.0.1", 29999),
                "client": ("127.0.0.1", 1),
            },
            receive,
            send,
        )
        try:
            with pytest.raises(StopIteration):
                coroutine.send(None)
        finally:
            coroutine.close()
        assert len(sent) == 2 and sent[0]["type"] == "http.response.start"
        assert sent[0]["status"] == status, sent
        response = {k.decode(): v.decode() for k, v in sent[0]["headers"]}
        assert response["cache-control"] == "no-store"
        assert response["x-content-type-options"] == "nosniff"
        return json.loads(sent[1]["body"]), response


@pytest.fixture
def direct(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("owned ASGI test attempted a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    return Direct(tmp_path)


def prepare(direct):
    csv = b"post_id,date,platform,text,impressions,likes,comments,shares\n" + b"".join(
        f"p{i},2026-10-01,linkedin,synthetic,100,5,2,1\n".encode() for i in range(6)
    )
    imported, _ = direct.request("/api/import", {"csv_base64": base64.b64encode(csv).decode()})
    selection = imported["selection"]
    activated, _ = direct.request(
        "/api/activate",
        {
            "selection": selection,
            "expected_sequence": imported["sequence"],
        },
    )
    plan, _ = direct.request(
        "/api/plan",
        {
            "selection": selection,
            "expected_sequence": activated["sequence"],
            "brief": "Workshop",
        },
    )
    assert len(plan["versions"]) == 5
    return selection, plan


def approved_draft(direct):
    selection, plan = prepare(direct)
    parent = plan["versions"][0]
    decision, _ = direct.request(
        "/api/decide",
        {
            "selection": selection,
            "version": parent,
            "expected_sequence": plan["sequence"],
            "approve": True,
        },
    )
    draft, _ = direct.request(
        "/api/draft",
        {
            "selection": selection,
            "version": parent,
            "expected_sequence": decision["sequence"],
        },
    )
    frame = {
        "selection": selection,
        "version": draft["version"],
        "expected_sequence": draft["sequence"],
    }
    preview, _ = direct.request("/api/preview", frame)
    assert preview["kind"] == "draft" and preview["body"]
    decision, _ = direct.request("/api/decide", frame | {"approve": True})
    return selection, draft["version"], decision["sequence"]


def test_owned_http_normal_journey_and_receipt_restart(direct, tmp_path):
    selection, version, sequence = approved_draft(direct)
    exported, _ = direct.request(
        "/api/export",
        {
            "selection": selection,
            "items": [version],
            "expected_sequence": sequence,
            "idempotency_key": "http-approved",
        },
    )
    assert len(exported["receipt"]["approval_event_ids"]) == 2
    assert all(base64.b64decode(exported[key]) for key in ("markdown_base64", "csv_base64"))
    restarted = Direct(tmp_path)
    replay, _ = restarted.request(
        "/api/receipt",
        {
            "selection": selection,
            "idempotency_key": "http-approved",
        },
    )
    assert replay["historical_replay"] is True
    for key in ("receipt", "markdown_base64", "csv_base64"):
        assert replay[key] == exported[key]
    inventory, _ = restarted.request("/api/history", {"selection": selection})
    revoked, _ = restarted.request(
        "/api/revoke",
        {
            "selection": selection,
            "version": version,
            "expected_sequence": inventory["sequence"],
        },
    )
    restarted.request(
        "/api/export",
        {
            "selection": selection,
            "items": [version],
            "expected_sequence": revoked["sequence"],
            "idempotency_key": "after-revocation",
        },
        status=409,
    )
    historical, _ = restarted.request(
        "/api/receipt",
        {
            "selection": selection,
            "idempotency_key": "http-approved",
        },
    )
    assert historical["markdown_base64"] == exported["markdown_base64"]


def test_unapproved_and_revoked_http_exports_refuse(direct):
    selection, plan = prepare(direct)
    frame = {
        "selection": selection,
        "items": [plan["versions"][0]],
        "expected_sequence": plan["sequence"],
        "idempotency_key": "unapproved",
    }
    value, _ = direct.request("/api/export", frame, status=409)
    assert set(value) == {"code"}
    parent = plan["versions"][0]
    decision, _ = direct.request(
        "/api/decide",
        {
            "selection": selection,
            "version": parent,
            "expected_sequence": plan["sequence"],
            "approve": True,
        },
    )
    revoked, _ = direct.request(
        "/api/revoke",
        {
            "selection": selection,
            "version": parent,
            "expected_sequence": decision["sequence"],
        },
    )
    direct.request("/api/export", frame | {"expected_sequence": revoked["sequence"]}, status=409)


@pytest.mark.parametrize("change", ["host", "origin", "cookie", "csrf"])
def test_real_route_boundary_refuses_before_import(direct, change):
    headers = dict(direct.headers)
    headers[
        {"host": "host", "origin": "origin", "cookie": "cookie", "csrf": "x-csrf-token"}[change]
    ] = "invalid"
    value, _ = direct.request("/api/import", {"csv_base64": ""}, headers=headers, status=409)
    assert set(value) == {"code"}
    assert not direct.host.review.database.exists()


def test_http_invalid_csv_and_untrusted_host_fields_refuse(direct):
    invalid, _ = direct.request(
        "/api/import",
        {
            "csv_base64": base64.b64encode(b"bad\n").decode(),
        },
        status=422,
    )
    assert invalid["code"] == "invalid_csv"
    assert not direct.host.review.database.exists()
    for field in ("actor_label", "assessment", "screen_scores", "database"):
        value, _ = direct.request("/api/import", {"csv_base64": "", field: "forged"}, status=422)
        assert value == {"code": "invalid_request"}
    assert not direct.host.review.database.exists()


def test_parent_revocation_invalidates_child_and_requires_new_decisions(direct):
    selection, version, sequence = approved_draft(direct)
    rows, _ = direct.request("/api/history", {"selection": selection})
    parent = next(
        row["version"]
        for row in rows["rows"]
        if (row["kind"] == "recommendation" and row["state"] == "approved")
    )
    revoked, _ = direct.request(
        "/api/revoke",
        {
            "selection": selection,
            "version": parent,
            "expected_sequence": sequence,
        },
    )
    rows, _ = direct.request("/api/history", {"selection": selection})
    assert next(row["state"] for row in rows["rows"] if row["version"] == version) == "draft"
    direct.request(
        "/api/export",
        {
            "selection": selection,
            "items": [version],
            "expected_sequence": revoked["sequence"],
            "idempotency_key": "revoked-parent",
        },
        status=409,
    )


def test_revocation_cas_and_authorization_failure_leave_approval_intact(direct):
    selection, version, sequence = approved_draft(direct)
    frame = {"selection": selection, "version": version, "expected_sequence": sequence}
    direct.request("/api/revoke", frame | {"expected_sequence": sequence - 1}, status=409)
    review = direct.host.review
    review.authorize = lambda actor, action, content: action != "revoke"
    direct.request("/api/revoke", frame, status=409)
    assert review.sequence(Selection.model_validate(selection)) == sequence
    rows, _ = direct.request("/api/history", {"selection": selection})
    assert next(row["state"] for row in rows["rows"] if row["version"] == version) == "approved"
