"""Compile an authored synthetic plan before admitting its one zero-dispatch operation.

This is application mock execution, not real Jev/Luna answers or independent quality.
Every actual request, native screen nonce, answer and proof exists before admission.
Unknown conditional repair requests are not fabricated and cannot be looked up.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ..adapters.compiled import CompiledCall, CompiledPorts
from ..adapters.provider import OfflineGateway
from ..adapters.screening import NativeScreen
from ..metrics.grounding import MetricsResolver
from ..pipeline import Pipeline
from ..pipeline.assembly import (
    plan_document,
    plan_support_document,
    recommendation_content,
    select_metrics,
)
from ..pipeline.ports import Assembly, Bindings, CallBinding, Candidate, PortRefusal, WorkflowPolicy
from ..shared.callledger import Ledger
from ..shared.callledger.ledger import LedgerError
from ..shared.callledger.models import (
    BudgetAuthority,
    CallContext,
    ChildBound,
    Limits,
    NormalizedUsage,
    OperationPlan,
    canonical_digest,
)
from ..shared.callledger.pricing import RequestEvidence
from ..shared.grounded.models import MetricSnapshot
from ..shared.grounded.validation import Policy, validate
from ..shared.providers.adapters import ModelSupport, Outcome, ProviderConfig, prepare_request
from ..shared.providers.captures import FixtureIndex, synthetic_capture
from ..shared.providers.controller import Provider
from ..shared.providers.models import GenerateRequest, TypedJudgmentRequest, TypedJudgmentResult
from ..shared.screen import ScreenPolicy
from ..shared.screen.models import HAZARDS

MODEL = "s9-authored-mock"
REPORTED = "s9-authored-mock-output"
VERDICTS = ("supports", "contradicts", "says_nothing", "unknown")
STAGES = tuple(
    prefix + phase
    for phase in ("initial", "repair")
    for prefix in ("screen.plan.", "plan.", "screen.support.", "support.")
)


def _config(typed):
    return ProviderConfig(
        schema_version=1,
        flavor="typesafe" if typed else "openai_responses",
        endpoint_id="s9-authored-offline",
        revision_sha256=canonical_digest("mock-compiler.v1"),
        models={
            MODEL: ModelSupport(
                generation=not typed,
                typed_judgment=typed,
                structured_output=not typed,
                image_input=False,
                streaming=False,
                temperature=False,
                reasoning_efforts=[],
                reported_models=[REPORTED],
            )
        },
    )


def support_request(assembly, item_ids):
    return TypedJudgmentRequest.model_validate(
        {
            "schema_version": 1,
            "kind": "typed_judgment",
            "model": MODEL,
            "state": assembly.text,
            "questions": {
                key: {
                    "type": "choice",
                    "instructions": "Judge whether the supplied metrics support "
                    "this exact item, including direction, scope and any performance claim.",
                    "criteria": {v: v for v in VERDICTS},
                }
                for key in item_ids
            },
        }
    )


@dataclass
class MockPlan:
    snapshot: MetricSnapshot
    brief: str
    pipeline: Pipeline
    bindings: Bindings
    ports: CompiledPorts
    ledger: Ledger
    allocation: object
    children: tuple[ChildBound, ...]
    cleanup: tuple = ()
    used: bool = False
    closed: bool = False

    def run(self):
        if self.used or self.closed:
            raise PortRefusal("compiled_operation_already_used")
        self.used = True
        try:
            return self.pipeline.plan(self.snapshot, self.brief, bindings=self.bindings)
        finally:
            self.finish()

    def finish(self):
        outcomes = []
        for child in self.children:
            if child.child_id in self.ports.completed:
                continue
            proof = canonical_digest(
                {
                    "allocation_id": self.allocation.allocation_id,
                    "child_id": child.child_id,
                    "undispatched": True,
                }
            )
            try:
                outcome = "skipped" if child.conditional else "cancelled_before_dispatch"
                self.ledger.finish_child(
                    self.allocation, child_id=child.child_id, outcome=outcome, proof_sha256=proof
                )
                outcomes.append((child.child_id, outcome))
            except LedgerError as error:
                # A failed cache result can already have terminal reuse accounting.
                # Preserve the public refusal rather than rewriting its ledger state.
                outcomes.append((child.child_id, str(error)))
        self.cleanup = tuple(outcomes)

    def close(self):
        if self.closed:
            return
        if not self.used:
            self.finish()
        self.ledger.close()
        self.closed = True


def compile_plan(
    database: Path,
    snapshot: MetricSnapshot,
    brief: str,
    candidates: tuple[Candidate, ...],
    *,
    namespace: str,
    screen_policy: ScreenPolicy,
    screen_scores: dict[str, float],
    support_verdicts: dict[str, str],
) -> MockPlan:
    """Explicit authored answers; no default passing judgments or hidden corpora.

    First-path compiler requires all authored candidates locally valid and selected.
    Repair/support outcomes not concretely compiled are refused by the original ports.
    """
    snapshot = MetricSnapshot.model_validate(snapshot.model_dump(mode="python"))
    if not isinstance(brief, str) or len(brief) > 4000:
        raise PortRefusal("brief_limit")
    if type(candidates) is not tuple or not 1 <= len(candidates) <= 10:
        raise PortRefusal("authored_candidates_required")
    candidates = tuple(Candidate.model_validate(c.model_dump(mode="python")) for c in candidates)
    if type(screen_policy) is not ScreenPolicy or screen_policy.required_method != "typed":
        raise PortRefusal("typed_mock_policy_required")
    if set(screen_scores) != set(HAZARDS):
        raise PortRefusal("complete_authored_screen_answers_required")
    workflow = WorkflowPolicy(
        screen_policy_sha256=screen_policy.sha256, required_method="typed_mock", origin="mock"
    )
    policy = Policy(screen_edition=screen_policy.sha256)
    projection = select_metrics(snapshot, workflow.max_metric_rows)
    selected = {m.metric_id for m in projection.selected}
    checked = []
    for candidate in candidates:
        if candidate.scope == "multi" or any(
            c.metric_id not in selected for c in candidate.citations
        ):
            raise PortRefusal("authored_candidate_outside_projection")
        item = validate(
            recommendation_content(candidate, snapshot.snapshot_id),
            MetricsResolver(snapshot),
            policy,
        )
        if item.report.failures:
            raise PortRefusal("authored_candidate_invalid")
        checked.append(item)
    ids = tuple(c.content.item.item_id for c in checked)
    if len(set(ids)) != len(ids) or set(support_verdicts) != set(ids):
        raise PortRefusal("exact_authored_support_answers_required")
    if any(value not in VERDICTS for value in support_verdicts.values()):
        raise PortRefusal("invalid_authored_support_verdict")
    table = projection.table()
    generation = snapshot.snapshot_id
    plan_assembly = Assembly.build(plan_document(brief, table), generation)
    support_assembly = Assembly.build(plan_support_document(checked, table), generation)
    if max(len(a.text.encode("utf-8")) for a in (plan_assembly, support_assembly)) > 32768:
        raise PortRefusal("input_too_large")
    generated = GenerateRequest.model_validate(
        {
            "schema_version": 1,
            "kind": "generate",
            "model": MODEL,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": plan_assembly.text}]}
            ],
            "max_output_tokens": 4096,
            "stream": False,
        }
    )
    support = support_request(support_assembly, ids)
    native_plan = NativeScreen.prepare(plan_assembly, policy=screen_policy, model=MODEL)
    native_support = NativeScreen.prepare(support_assembly, policy=screen_policy, model=MODEL)
    requests = {
        "screen.plan.initial": native_plan.request,
        "plan.initial": generated,
        "screen.support.initial": native_support.request,
        "support.initial": support,
    }
    assemblies = {
        stage: plan_assembly if "plan" in stage else support_assembly for stage in requests
    }
    configs = {False: _config(False), True: _config(True)}
    deadline = (datetime.now(UTC) + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")
    operation = "mock-" + uuid4().hex
    authority = BudgetAuthority(
        schema_version=1,
        authority_id=operation,
        scope_sha256=canonical_digest({"generation": generation, "workflow": workflow.digest}),
        cap_usd="0",
        max_outbound_attempts=0,
        run_deadline_utc=deadline,
    )
    limits = Limits(
        schema_version=1,
        max_attempts_total=1,
        max_content_repairs=0,
        operation_deadline_s=120,
        attempt_timeout_s=30,
        run_deadline_utc=deadline,
        max_outbound_attempts=0,
        max_concurrent_operations=1,
        max_request_bytes=262144,
        max_response_bytes=262144,
        max_questions=32,
        max_choice_options=8,
        max_total_output_tokens=4096,
    )
    root = CallContext(
        schema_version=1,
        authority_id=authority.authority_id,
        run_id="s9-local-authored-mock",
        operation_id=operation,
        child_id="whole",
        task_id="content-strategy",
        span_id=operation,
        consumer_namespace=namespace,
        purpose="s9.plan",
        source_generation=generation,
        consumer_context_sha256=workflow.digest,
        policy_sha256=screen_policy.sha256,
        template_sha256=canonical_digest("s9-authored-plan.v1"),
        config_sha256=canonical_digest([c.sha256 for c in configs.values()]),
    )
    contexts = {
        stage: root.model_copy(
            update={
                "child_id": stage,
                "span_id": stage,
                "parent_span_id": operation,
                "purpose": "s9." + stage,
            }
        )
        for stage in STAGES
    }
    evidence, captures, children = [], {False: [], True: []}, []
    for stage in STAGES:
        typed = not stage.startswith("plan.")
        config = configs[typed]
        bound = canonical_digest({"synthetic_no_dispatch_stage": stage, "operation": operation})
        request = requests.get(stage)
        children.append(
            ChildBound(
                child_id=stage,
                purpose="s9." + stage,
                provider_config_sha256=config.sha256,
                model=MODEL,
                bound_evidence_sha256=bound,
                max_attempts=0,
                max_repairs=0,
                input_token_maximum=0,
                output_token_maximum=4096 if not typed else None,
                fee_maximum_usd="0",
                reserved_usd_per_attempt="0",
                request_shape_limit_sha256=canonical_digest(limits.model_dump(mode="json")),
                conditional=stage.endswith("repair"),
            )
        )
        if request is None:
            continue
        prepared = prepare_request(request, config=config, context=contexts[stage], limits=limits)
        evidence.append(
            RequestEvidence(
                schema_version=1,
                bound_evidence_sha256=bound,
                request_identity_sha256=prepared.request_identity_sha256,
                dispatched_envelope_sha256=prepared.dispatched_envelope_sha256,
                input_token_count=0,
                output_token_maximum=4096 if not typed else None,
                proof_sha256=canonical_digest(
                    {
                        "edition": "authored-zero-dispatch-bound.v1",
                        "request": prepared.request_identity_sha256,
                    }
                ),
            )
        )
        answer = None
        parsed = None
        if stage.startswith("screen."):
            answer = TypedJudgmentResult(
                schema_version=1,
                model_reported=REPORTED,
                question_spec_sha256=request.question_spec_sha256,
                answers={
                    key: {"type": "noul", "noul": value} for key, value in screen_scores.items()
                },
            )
        elif stage.startswith("support."):
            answer = TypedJudgmentResult(
                schema_version=1,
                model_reported=REPORTED,
                question_spec_sha256=request.question_spec_sha256,
                answers={
                    key: {
                        "type": "choice",
                        "choice": verdict,
                        "probabilities": {v: float(v == verdict) for v in VERDICTS},
                        "confidence": 1.0,
                    }
                    for key, verdict in support_verdicts.items()
                },
            )
        else:
            parsed = {"candidates": [c.model_dump(mode="json") for c in candidates]}
        if answer is not None:
            answer.validate_for(request)
        outcome = Outcome("ok", REPORTED, NormalizedUsage(), None, parsed=parsed, typed=answer)
        captures[typed].append(
            synthetic_capture(
                prepared,
                context=contexts[stage],
                outcome=outcome,
                capture_id=operation + "-" + stage,
                review_receipt_sha256=canonical_digest(
                    {"authored_compiler": "v1", "stage": stage, "not_independent_review": True}
                ),
            )
        )
    # No request registration or fixture mutation occurs after these constructors.
    providers = {
        typed: Provider(
            config,
            mode="mock",
            request_evidence=evidence,
            fixtures=FixtureIndex(captures[typed]),
            capture_mode="fixture_replay",
        )
        for typed, config in configs.items()
    }
    ledger = Ledger(database, authority=authority, trusted_requests=evidence)
    try:
        plan = OperationPlan(
            schema_version=1,
            operation_id=operation,
            authority_id=authority.authority_id,
            context_sha256=canonical_digest(root.model_dump(mode="json")),
            children=children,
        )
        allocation = providers[False].admit_operation(
            plan, ledger=ledger, budget=authority, context=root, limits=limits
        )
        bindings = {
            stage: CallBinding(
                "s9." + stage, ledger, authority, contexts[stage], limits, allocation
            )
            for stage in STAGES
        }
        calls, screens = {}, {}
        for stage, request in requests.items():
            typed = type(request) is TypedJudgmentRequest
            call = CompiledCall(
                assemblies[stage],
                request,
                bindings[stage],
                OfflineGateway(providers[typed]),
                tuple((c.content.item.item_id, c.content.item.content_hash) for c in checked)
                if stage.startswith("support.")
                else (),
            )
            if stage.startswith("screen."):
                native = native_plan if "plan" in stage else native_support
                screens["s9." + stage] = (
                    call,
                    NativeScreen(native, provider=providers[typed], policy=screen_policy),
                )
            else:
                calls["s9." + stage] = call
        ports = CompiledPorts(calls, screens)
        pipeline = Pipeline(
            screen=ports, generator=ports, support=ports, policy=workflow, grounded_policy=policy
        )
        return MockPlan(
            snapshot,
            brief,
            pipeline,
            Bindings(bindings),
            ports,
            ledger,
            allocation,
            tuple(children),
        )
    except BaseException:
        ledger.close()
        raise
