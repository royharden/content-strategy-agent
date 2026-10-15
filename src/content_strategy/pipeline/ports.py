"""App/test staging seams, not canonical S3/S6 implementations or funded authority."""

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Protocol

from pydantic import BeforeValidator, Field, PlainSerializer, model_validator

from ..shared.grounded.identity import canonical_json, identity_hash
from ..shared.grounded.models import Digest, Identifier, MetricCitation, Record, Text
from ..shared.grounded.validation import Checked, EditorialLiteral


class WorkflowPolicy(Record):
    edition: Literal["workflow.v1"] = "workflow.v1"
    screen_policy_sha256: Digest
    required_method: Literal["rules", "typed_mock", "typed_replay", "typed_live"]
    origin: Literal["mock", "replay", "live"]
    max_metric_rows: int = Field(default=40, ge=1, le=40)

    @property
    def digest(self):
        return identity_hash(self.model_dump(mode="python"))

    @model_validator(mode="after")
    def explicit_origin_method(self):
        allowed = {
            "mock": {"rules", "typed_mock"},
            "replay": {"rules", "typed_replay"},
            "live": {"typed_live"},
        }
        if self.required_method not in allowed[self.origin]:
            raise ValueError("execution_origin_method_mismatch")
        return self


@dataclass(frozen=True)
class Assembly:
    text: str
    source_generation: str

    @classmethod
    def build(cls, document, generation):
        try:
            text = canonical_json(document)
            text.encode("utf-8")
        except ValueError:
            raise PortRefusal("invalid_utf8_assembly") from None
        return cls(text, generation)

    @property
    def digest(self):
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class PortRefusal(ValueError):
    pass


@dataclass(frozen=True)
class CallBinding:
    purpose: str
    ledger: object
    budget: object
    context: object
    limits: object
    allocation: object

    def check(self, generation: str, policy: WorkflowPolicy):
        if (
            getattr(self.context, "purpose", None) != self.purpose
            or getattr(self.context, "source_generation", None) != generation
            or getattr(self.context, "policy_sha256", None) != policy.digest
        ):
            raise PortRefusal("context_mismatch")
        attempts = getattr(self.limits, "max_attempts_total", None)
        repairs = getattr(self.limits, "max_content_repairs", None)
        if (
            type(attempts) is not int
            or not 1 <= attempts <= 2
            or type(repairs) is not int
            or repairs != 0
        ):
            raise PortRefusal("owner_limits_required")
        if any(
            value is None
            for value in (self.ledger, self.budget, self.context, self.limits, self.allocation)
        ):
            raise PortRefusal("funded_binding_required")


class Bindings:
    def __init__(self, stages: dict[str, CallBinding]):
        self._stages = dict(stages)
        values = tuple(self._stages.values())
        if values and any(
            value.ledger is not values[0].ledger
            or value.budget is not values[0].budget
            or value.allocation is not values[0].allocation
            for value in values
        ):
            raise PortRefusal("whole_operation_binding_mismatch")

    def get(self, stage, generation, policy):
        binding = self._stages.get(stage)
        if binding is None:
            raise PortRefusal("unfunded_stage")
        if binding.purpose != "s9." + stage:
            raise PortRefusal("stage_purpose_mismatch")
        binding.check(generation, policy)
        return binding

    def require(self, stages, generation, policy):
        for stage in stages:
            self.get(stage, generation, policy)


class ScreenVerdict(Record):
    """App projection of a trusted owner result, never an S6 transport replacement."""

    input_sha256: Digest
    normalized_sha256: Digest
    source_generation: Digest
    policy_sha256: Digest
    transform_version: Identifier
    method: Literal["rules", "typed_mock", "typed_replay", "typed_live"]
    coverage: Literal["complete", "partial"]
    normalized_bytes: int = Field(ge=0)
    decision: Literal["pass", "needs_human"]
    deterministic_flags: tuple[Identifier, ...] = ()
    diagnostic_notices: tuple[Identifier, ...] = ()
    adapter_status: Literal["ok", "unavailable", "invalid", "error"]
    operating_authority_sha256: Digest | None = None
    accounting_ref: Identifier | None = None


class Candidate(Record):
    scope: Identifier
    text: Text
    citations: tuple[MetricCitation, ...]
    editorial: tuple[EditorialLiteral, ...] = ()


class GenerationResult(Record):
    status: Literal["ok", "refused", "invalid_output", "unsupported", "error"]
    candidates: tuple[Candidate, ...] = Field(default=(), max_length=10)
    origin: Literal["mock", "replay", "live"]
    model_reported: Identifier | None = None
    accounting_ref: Identifier | None = None


class SupportDecision(Record):
    item_id: Identifier
    verdict: Literal["supports", "contradicts", "says_nothing", "unknown"]


class SupportResult(Record):
    status: Literal["ok", "unsupported", "error"]
    decisions: tuple[SupportDecision, ...]
    method: Literal["rule_direction", "luna", "jev"]
    origin: Literal["mock", "replay", "live"]
    accounting_ref: Identifier | None = None


class ScreenPort(Protocol):
    def check(self, assembly: Assembly, *, binding: CallBinding) -> ScreenVerdict: ...


class GenerationPort(Protocol):
    def generate(self, assembly: Assembly, *, binding: CallBinding) -> GenerationResult: ...


class SupportPort(Protocol):
    def judge(
        self, items: tuple[Checked, ...], assembly: Assembly, *, binding: CallBinding
    ) -> SupportResult: ...


def _probability(value):
    if type(value) not in {str, int, float, Decimal} or len(str(value)) > 1024:
        raise ValueError("finite_probability_required")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("finite_probability_required") from None
    if not result.is_finite() or not 0 <= result <= 1:
        raise ValueError("finite_probability_required")
    return result


Probability = Annotated[
    Decimal, BeforeValidator(_probability), PlainSerializer(str, return_type=str)
]


class TagChoice(Record):
    value: Identifier
    confidence: Probability


class TagResult(Record):
    topic: TagChoice
    format: TagChoice
    method: Literal["luna", "jev"]
    model_reported: Identifier


class TagPort(Protocol):
    def classify(self, assembly: Assembly, *, binding: CallBinding) -> TagResult: ...
