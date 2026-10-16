"""Explicit same-origin HTTP factory. Importing never creates an app, DB or listener."""

import re
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles

from ..ingest import IngestError
from ..metrics import AnalysisConfig
from ..pipeline.ports import PortRefusal
from ..platforms import check_target
from ..runtime.examples import authored_draft_input, authored_plan_inputs, demo_csv
from ..shared.grounded.audit import GateError
from ..shared.screen.models import HAZARDS
from ..storage import StorageError
from .application import Planned, PlanningHost
from .security import SessionGuard
from .views import bundle_view, report_view, selection_view
from .wire import (
    MAX_BODY,
    MAX_IMPORT_BODY,
    CurrentInput,
    DecisionInput,
    DraftInput,
    EditInput,
    ExportInput,
    ImportInput,
    PlanInput,
    ReceiptInput,
    SelectedInput,
    VersionInput,
    parse_input,
)

SECURITY_HEADERS = [
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (
        b"content-security-policy",
        b"default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    ),
]


def _headers(scope):
    return [(key.decode("latin-1"), value.decode("latin-1")) for key, value in scope["headers"]]


def _closed_error(error):
    code = str(error)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
        code = "request_refused"
    return JSONResponse({"code": code}, status_code=409)


class LocalBoundary:
    def __init__(self, app, *, guard):
        self.app, self.guard = app, guard

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def guarded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in {key for key, _ in SECURITY_HEADERS}
                ]
                message = {**message, "headers": headers + SECURITY_HEADERS}
            await send(message)

        try:
            path, method = scope.get("path", ""), scope.get("method", "")
            if not path.startswith("/api/") or (path == "/api/session" and method == "GET"):
                self.guard.bootstrap(_headers(scope))
            else:
                self.guard.check(_headers(scope), mutation=method not in {"GET", "HEAD"})
            await self.app(scope, receive, guarded_send)
        except GateError as error:
            if not started:
                await _closed_error(error)(scope, receive, guarded_send)
        except Exception:
            # Never send exception text, stack, raw input or a path to the browser.
            if not started:
                await JSONResponse({"code": "internal_error"}, status_code=500)(
                    scope, receive, guarded_send
                )


async def _input(request, kind):
    cap = MAX_IMPORT_BODY if kind is ImportInput else MAX_BODY
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            raise ValueError("invalid_request")
        chunks.append(chunk)
    return parse_input(b"".join(chunks), kind)


def create_app(host: PlanningHost, guard: SessionGuard, *, assets: Path | None = None) -> FastAPI:
    """Caller supplies the trusted local host and exact registered loopback origin.

    This application exposes authored mock execution explicitly. It has no live
    mode, provider credential fields, assessment submission, automatic approvals,
    CORS relaxation, actor selector or data-path selector.
    """
    if type(host) is not PlanningHost or type(guard) is not SessionGuard:
        raise GateError("trusted_host_and_session_required")
    app = FastAPI(title="Content Strategy Agent", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalBoundary, guard=guard)
    review = host.review

    async def refused(_request, error):
        return _closed_error(error)

    async def invalid(_request, _error):
        return JSONResponse({"code": "invalid_request"}, status_code=422)

    async def invalid_csv(_request, error):
        return JSONResponse(
            {"code": "invalid_csv", "issues": [asdict(issue) for issue in error.issues]},
            status_code=422,
        )

    for error_type in (GateError, StorageError, PortRefusal):
        app.add_exception_handler(error_type, refused)
    app.add_exception_handler(ValueError, invalid)
    app.add_exception_handler(RequestValidationError, invalid)
    app.add_exception_handler(IngestError, invalid_csv)

    @app.get("/api/session")
    async def session(request: Request):
        cookie, csrf = guard.bootstrap(_headers(request.scope))
        return JSONResponse(
            {
                "csrf": csrf,
                "execution_origin": "authored_synthetic_mock",
                "quality_measurement": False,
                "targets": {
                    scope: check_target(scope, "").supported for scope in ("linkedin", "x")
                },
            },
            headers={"set-cookie": cookie},
        )

    @app.get("/api/example")
    async def example():
        return Response(
            demo_csv(),
            media_type="text/csv; charset=utf-8",
            headers={"content-disposition": 'attachment; filename="synthetic-example.csv"'},
        )

    @app.post("/api/import")
    async def import_csv(request: Request):
        value = await _input(request, ImportInput)
        retained = review.import_csv(value.csv_bytes(), config=AnalysisConfig(value.clock))
        return {
            "selection": selection_view(retained),
            "activated": False,
            "sequence": review.sequence(value_selection(retained)),
        }

    @app.post("/api/report")
    async def report(request: Request):
        value = await _input(request, SelectedInput)
        return report_view(review.report(value.selection))

    @app.post("/api/activate")
    async def activate(request: Request):
        value = await _input(request, CurrentInput)
        return {
            "sequence": review.activate(value.selection, expected_sequence=value.expected_sequence)
        }

    @app.post("/api/history")
    async def history(request: Request):
        value = await _input(request, SelectedInput)
        return {
            "rows": [
                {
                    "version": row.version.model_dump(mode="json"),
                    "kind": row.kind,
                    "parent_id": row.parent_id,
                    "parent_revision": row.parent_revision,
                    "state": row.state,
                }
                for row in review.history(value.selection)
            ],
            "sequence": review.sequence(value.selection),
        }

    @app.post("/api/plan")
    async def plan(request: Request):
        value = await _input(request, PlanInput)
        review._allow("plan")
        review.require_context(value.selection, expected_sequence=value.expected_sequence)
        candidates, verdicts = authored_plan_inputs(review.report(value.selection).report.snapshot)
        if not candidates:
            result = Planned(
                (), value.expected_sequence, True, 0, (("insufficient_citable_data",),)
            )
        else:
            result = host.run_authored_plan(
                value.selection,
                value.brief,
                candidates,
                screen_scores=dict.fromkeys(HAZARDS, 0.01),
                support_verdicts=verdicts,
                expected_sequence=value.expected_sequence,
            )
        return {
            "versions": [version.model_dump(mode="json") for version in result.versions],
            "sequence": result.sequence,
            "underfilled": result.underfilled,
            "proposed": result.proposed,
            "dropped_codes": result.dropped_codes,
            "execution_origin": result.execution_origin,
            "quality_measurement": False,
        }

    @app.post("/api/preview")
    async def preview(request: Request):
        value = await _input(request, VersionInput)
        checked, assessment, sequence = review.preview(
            value.selection, value.version, expected_sequence=value.expected_sequence
        )
        return {
            "version": value.version.model_dump(mode="json"),
            "body": checked.rendered,
            "editable_text": checked.content.item.text,
            "sequence": sequence,
            "scope": checked.content.item.scope,
            "kind": checked.content.item.kind,
            "evidence": [metric.model_dump(mode="json") for metric in checked.evidence],
            "assessment": assessment.model_dump(mode="json"),
            "execution_origin": "authored_synthetic_mock",
            "quality_measurement": False,
        }

    @app.post("/api/decide")
    async def decide(request: Request):
        value = await _input(request, DecisionInput)
        state = review.decide(
            value.selection,
            value.version,
            approve=value.approve,
            expected_sequence=value.expected_sequence,
        )
        return {"state": state, "sequence": review.require_context(value.selection)}

    @app.post("/api/revoke")
    async def revoke(request: Request):
        value = await _input(request, VersionInput)
        return {
            "sequence": review.revoke(
                value.selection, value.version, expected_sequence=value.expected_sequence
            )
        }

    @app.post("/api/draft")
    async def draft(request: Request):
        value = await _input(request, DraftInput)
        parent = review.read(value.selection, value.version)
        result = host.run_authored_draft(
            value.selection,
            value.version,
            value.brief,
            authored_draft_input(parent),
            screen_scores=dict.fromkeys(HAZARDS, 0.01),
            support_verdict="supports",
            expected_sequence=value.expected_sequence,
        )
        return {
            "version": result.version.model_dump(mode="json") if result.version else None,
            "sequence": result.sequence,
            "proposed": result.proposed,
            "dropped_codes": result.dropped_codes,
            "execution_origin": result.execution_origin,
        }

    @app.post("/api/edit")
    async def edit(request: Request):
        value = await _input(request, EditInput)
        result = host.run_authored_edit(
            value.selection,
            value.version,
            value.text,
            screen_scores=dict.fromkeys(HAZARDS, 0.01),
            support_verdict="supports",
            expected_sequence=value.expected_sequence,
        )
        return {
            "version": result.version.model_dump(mode="json") if result.version else None,
            "sequence": result.sequence,
            "dropped_codes": result.dropped_codes,
            "execution_origin": result.execution_origin,
        }

    @app.post("/api/export")
    async def export(request: Request):
        value = await _input(request, ExportInput)
        return bundle_view(
            review.export(
                value.selection,
                idempotency_key=value.idempotency_key,
                items=value.items,
                expected_sequence=value.expected_sequence,
            )
        )

    @app.post("/api/receipt")
    async def receipt(request: Request):
        value = await _input(request, ReceiptInput)
        return bundle_view(review.download_receipt(value.selection, value.idempotency_key))

    @app.get("/api/download/{format}")
    async def download(format: str, request: Request):
        parameters = request.query_params
        keys = {"dataset_id", "snapshot_id", "key"}
        if (
            format not in {"md", "csv"}
            or set(parameters) != keys
            or any(len(parameters.getlist(key)) != 1 for key in keys)
        ):
            raise ValueError("invalid_request")
        value = ReceiptInput.model_validate(
            {
                "selection": {
                    "dataset_id": parameters["dataset_id"],
                    "snapshot_id": parameters["snapshot_id"],
                },
                "idempotency_key": parameters["key"],
            }
        )
        bundle = review.download_receipt(value.selection, value.idempotency_key)
        return Response(
            bundle.markdown if format == "md" else bundle.csv,
            media_type="text/markdown" if format == "md" else "text/csv",
            headers={"content-disposition": f'attachment; filename="approved-content.{format}"'},
        )

    if assets is not None:
        assets = Path(assets).resolve()
        if not assets.is_dir() or not (assets / "index.html").is_file():
            raise GateError("built_assets_required")
        app.mount("/", StaticFiles(directory=assets, html=True), name="web")
    return app


def value_selection(retained):
    from .service import Selection

    return Selection.model_validate(selection_view(retained))
