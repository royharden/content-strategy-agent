"""Source-only synthetic validity adapter; no corpus discovery, IO or model dispatch.

This contract is not admission of the existing DEV/Gold corpus schema. Public replay
metrics retain their supplied IDs and values and never acquire producer authority.
Only ``to_outcomes`` reads synthetic reference labels.
"""

import hashlib
from datetime import datetime

from ..metrics.grounding import MetricsResolver
from ..shared.evalkit.identity import canonical_bytes
from ..shared.evalkit.models import (
    FieldLabels,
    GoldRecord,
    MetricRow,
    MetricSpec,
    Outcome,
    Prediction,
    PublicMethodInput,
    PublicProjectionPolicy,
    SourceRef,
)
from ..shared.evalkit.reporting import metric_row
from ..shared.evalkit.runner import SourceView
from ..shared.evalkit.statistics import accuracy
from ..shared.grounded.models import Metric
from ..shared.grounded.validation import Content, Policy, validate
from .replay_bridge import bind_authored_snapshot, public_identity

VERSION = "s9-source-only-validity.v1"
_PRIVATE = frozenset(
    {
        "gold",
        "label_payload",
        "label_source",
        "label_provenance_ref",
        "hidden_rubric",
        "family",
        "trap",
        "group_id",
        "expected",
        "correct",
    }
)
_PAYLOAD_FIELDS = {"content", "metrics", "public_contexts", "frozen_at", "source_ref"}


def _public(payload):
    if isinstance(payload, dict):
        if _PRIVATE.intersection(payload):
            raise ValueError("scorer_metadata_in_public_input")
        for value in payload.values():
            _public(value)
    elif isinstance(payload, list):
        for value in payload:
            _public(value)


def _source_ref(payload):
    if type(payload) is not dict or set(payload) != _PAYLOAD_FIELDS:
        raise ValueError("source_only_public_shape")
    _public(payload)
    return SourceRef.model_validate_json(canonical_bytes(payload["source_ref"]))


class ReplayValidityAdapter:
    """One deterministic method and its synthetic scorer, using canonical evalkit ports."""

    def __init__(self, policy: Policy, *, method: str = "s9-grounded-validity"):
        self.policy = Policy.model_validate(policy.model_dump(mode="python"))
        self.method = method
        self.version = VERSION
        self.config_sha256 = hashlib.sha256(
            canonical_bytes({"adapter": VERSION, "policy": self.policy.model_dump(mode="json")})
        ).hexdigest()

    def validate_gold(self, record: GoldRecord) -> None:
        record = GoldRecord.model_validate(record.model_dump(mode="python"))
        labels = record.label_payload
        if (
            record.domain_kind != VERSION
            or record.label_source != "synthetic"
            or not isinstance(labels, FieldLabels)
            or set(labels.labels) != {"validity"}
            or labels.labels["validity"].presence != "present"
            or type(labels.labels["validity"].value) is not bool
        ):
            raise ValueError("source_only_synthetic_validity_label_required")

    def to_public_input(self, record: GoldRecord, source_view: SourceView) -> PublicMethodInput:
        # Reference labels are intentionally not inspected or projected here.
        if (
            not isinstance(source_view, SourceView)
            or source_view.status != "available"
            or source_view.input_sha256 != record.input_sha256
            or hashlib.sha256(canonical_bytes(source_view.public_payload)).hexdigest()
            != record.input_sha256
            or _source_ref(source_view.public_payload) != record.source_ref
        ):
            raise ValueError("public_source_identity_changed")
        return PublicMethodInput.model_validate_json(
            canonical_bytes(
                {
                    "item_id": record.item_id,
                    "public_payload": source_view.public_payload,
                    "input_sha256": record.input_sha256,
                    "public_config_refs": [VERSION, self.config_sha256],
                }
            )
        )

    def predict(self, public_input: PublicMethodInput) -> Prediction:
        public_input = PublicMethodInput.model_validate(public_input.model_dump(mode="python"))
        payload = public_input.public_payload
        refs = ()
        try:
            ref = _source_ref(payload)
            refs = (ref,)
            if hashlib.sha256(
                canonical_bytes(payload)
            ).hexdigest() != public_input.input_sha256 or public_input.public_config_refs != (
                VERSION,
                self.config_sha256,
            ):
                raise ValueError("public_input_binding_changed")
            content = Content.model_validate_json(canonical_bytes(payload["content"]))
            if type(payload["metrics"]) is not list or type(payload["public_contexts"]) is not list:
                raise ValueError("public_replay_arrays_required")
            metrics = tuple(
                Metric.model_validate_json(canonical_bytes(value)) for value in payload["metrics"]
            )
            contexts = []
            for frame in payload["public_contexts"]:
                if type(frame) is not dict or set(frame) != {"source", "config", "tag_provenance"}:
                    raise ValueError("public_context_frame_required")
                source = frame["source"]
                if ref.sha256 != source["original_byte_sha256"]:
                    raise ValueError("original_source_reference_changed")
                contexts.append(
                    public_identity(
                        source,
                        frame["config"],
                        frame["tag_provenance"],
                        original_csv=source["csv_text"].encode("utf-8"),
                    )
                )
            frozen_at = datetime.fromisoformat(payload["frozen_at"])
            bound = bind_authored_snapshot(
                metrics,
                (content.item.snapshot_id,),
                tuple(contexts),
                frozen_at=frozen_at,
            )
            checked = validate(content, MetricsResolver(bound.snapshot), self.policy)
            valid = checked.report.structural_status == "valid"
            domain = {
                "valid": valid,
                "failure_codes": [failure.code for failure in checked.report.failures],
                "evidence_origin": bound.evidence_origin,
                "producer_authority": bound.producer_authority,
                "public_context_sha256": bound.public_context_sha256,
            }
            status, output, issues = "ok", valid, ()
        except (ValueError, TypeError, KeyError, AttributeError):
            # An unusable replay is an observed error, never a successful rejection.
            status, domain, output = "invalid", None, None
            issues = ("invalid_public_replay_input",)
        return Prediction(
            item_id=public_input.item_id,
            method=self.method,
            method_version=self.version,
            config_sha256=self.config_sha256,
            model=None,
            origin="synthetic",
            status=status,
            domain_payload=domain,
            machine_output=output,
            human_effective_output=None,
            human_provenance_ref=None,
            issues=issues,
            ledger_refs=(),
            source_refs=refs,
        )

    def validate_prediction(self, prediction: Prediction) -> None:
        prediction = Prediction.model_validate(prediction.model_dump(mode="python"))
        if (
            prediction.method != self.method
            or prediction.method_version != self.version
            or prediction.config_sha256 != self.config_sha256
            or prediction.origin != "synthetic"
            or prediction.model is not None
            or prediction.human_effective_output is not None
            or prediction.human_provenance_ref is not None
            or prediction.ledger_refs
        ):
            raise ValueError("synthetic_method_binding_changed")
        if prediction.status != "ok":
            return
        payload = prediction.domain_payload
        if (
            payload is None
            or set(payload)
            != {
                "valid",
                "failure_codes",
                "evidence_origin",
                "producer_authority",
                "public_context_sha256",
            }
            or type(payload["valid"]) is not bool
            or prediction.machine_output is not payload["valid"]
            or payload["producer_authority"] is not False
            or payload["evidence_origin"] != "authored_synthetic_replay"
            or type(payload["failure_codes"]) is not list
            or any(type(code) is not str or not code for code in payload["failure_codes"])
            or payload["valid"] != (not payload["failure_codes"])
            or type(payload["public_context_sha256"]) is not str
            or len(payload["public_context_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in payload["public_context_sha256"])
            or len(prediction.source_refs) != 1
        ):
            raise ValueError("invalid_validity_prediction")

    def to_outcomes(
        self, machine: Prediction, gold: GoldRecord, policy: object
    ) -> tuple[Outcome, ...]:
        self.validate_gold(gold)
        self.validate_prediction(machine)
        if (
            machine.item_id != gold.item_id
            or policy != self.policy
            or (machine.status == "ok" and machine.source_refs != (gold.source_ref,))
        ):
            raise ValueError("scorer_identity_or_policy_changed")
        expected = gold.label_payload.labels["validity"].value
        observed = machine.machine_output if machine.status == "ok" else None
        return (
            Outcome(
                item_id=gold.item_id,
                group_id=gold.group_id,
                dataset=gold.dataset,
                split=gold.split,
                method=machine.method,
                field="validity",
                **{"class": None},
                eligibility="eligible",
                status=machine.status,
                correct=(observed == expected) if machine.status == "ok" else None,
                predicted=observed,
                expected=expected,
                human_touched_prediction=False,
                evidence_origin=machine.origin,
                issues=machine.issues,
                ledger_refs=machine.ledger_refs,
            ),
        )

    def metric_specs(self) -> tuple[MetricSpec, ...]:
        return (
            MetricSpec(
                metric="accuracy",
                statistic_version=VERSION,
                population="as_frozen",
                denominator_policy="all-eligible.v1",
                zero_denominator_reason="zero_support",
                averaging="none",
            ),
        )

    def public_projection_policy(self) -> PublicProjectionPolicy:
        return PublicProjectionPolicy(
            mode="aggregate_only",
            allowed_dimensions=(),
            allowed_value_sets={},
            allowed_numeric_metrics=("value", "numerator", "denominator", "corpus_N", "error_N"),
            synthetic_example_refs=(),
        )

    def report(
        self,
        outcomes: tuple[Outcome, ...],
        expected_item_ids: tuple[str, ...],
        *,
        dataset_alias: str,
        split: str,
    ) -> MetricRow:
        return metric_row(
            outcomes,
            expected_item_ids,
            self.metric_specs()[0],
            accuracy,
            method=self.method,
            dataset_alias=dataset_alias,
            split=split,
            config_ref=self.config_sha256,
            field="validity",
        )
