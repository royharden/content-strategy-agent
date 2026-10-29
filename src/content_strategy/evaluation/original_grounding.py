"""Original author001 grounding wire consumer, gated by a trusted custodian host.

No corpus, label store or alternate wire is created. Actual owner metadata is not
available to the method author. The CLI therefore refuses without host injection;
it does not treat a caller-written JSON file or a path as read authorization.
"""

import argparse
import hashlib
import json
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ..shared.evalkit.identity import canonical_bytes
from ..shared.evalkit.models import (
    DomainLabels,
    GoldRecord,
    Manifest,
    MetricSpec,
    Outcome,
    PinnedReference,
    Prediction,
    PublicMethodInput,
    SourceRef,
)
from ..shared.evalkit.reporting import metric_row
from ..shared.evalkit.runner import MethodConfig, SourceView, compare
from ..shared.evalkit.statistics import accuracy
from ..shared.grounded.identity import identity_hash
from ..shared.grounded.models import EvidenceKey, Metric
from ..shared.grounded.validation import Content, Policy, validate

VERSION = "s9-original-grounding.v1"
METHOD = "actual-grounded-validator"
SUPPORTS = {
    **{
        "invalid_citation_" + name: 6
        for name in (
            "unknown_id",
            "wrong_snapshot",
            "wrong_value",
            "wrong_unit",
            "insufficient_n",
            "unavailable",
            "empty_citation",
            "conflicting_citation",
            "hidden_number",
            "wrong_platform",
        )
    },
    "valid_recommendation": 20,
    "valid_editorial_draft": 20,
    "invalid_disguised_performance_draft": 20,
}
_PRIVATE = {
    "fixture_id",
    "split",
    "expected",
    "category",
    "gold",
    "label_payload",
    "private_source_family_ids",
    "required_reference_ids",
    "contentGroundReferences",
    "what_bug_this_catches",
    "label_provenance",
    "human_gold",
    "human_agreement_measured",
}
_GOLD_FIELDS = {
    "schema_version",
    "fixture_id",
    "split",
    "method_input_sha256",
    "private_source_family_ids",
    "required_reference_ids",
    "contentGroundReferences",
    "what_bug_this_catches",
    "label_provenance",
    "human_gold",
    "human_agreement_measured",
    "conflicts",
    "expected",
    "unknown_required_reference_count",
}


class NeedsOwnerMetadata(ValueError):
    """An unresolved admission/comparator is never a successful floor result."""


def _pairs(pairs):
    result, normalized = {}, set()
    for key, value in pairs:
        nfc = unicodedata.normalize("NFC", key)
        if nfc in normalized:
            raise ValueError("duplicate_json_key")
        normalized.add(nfc)
        result[key] = value
    return result


def _no_number(value):
    raise ValueError("noninteger_json_number")


def _decode(data):
    return json.loads(
        data, object_pairs_hook=_pairs, parse_float=_no_number, parse_constant=_no_number
    )


def _public(value):
    if isinstance(value, dict):
        if _PRIVATE.intersection(value):
            raise ValueError("private_scorer_metadata_in_method")
        for item in value.values():
            _public(item)
    elif isinstance(value, list):
        for item in value:
            _public(item)


class SuppliedMetrics:
    """CurrentEvidence over original DTOs, without manufacturing a MetricSnapshot."""

    def __init__(self, metrics: tuple[Metric, ...], generation: str):
        EvidenceKey(generation=generation, scope="check", evidence_id="check")
        self.generation = generation
        self.metrics = {}
        for metric in metrics:
            key = (metric.snapshot_id, metric.scope, metric.metric_id)
            if key in self.metrics:
                raise ValueError("ambiguous_supplied_metric")
            self.metrics[key] = metric

    def current_generation(self, scope: str) -> str:
        return self.generation

    def resolve(self, key: EvidenceKey) -> Metric | None:
        if key.generation != self.generation:
            return None
        return self.metrics.get((key.generation, key.scope, key.evidence_id))


@dataclass(frozen=True)
class CustodianAdmission:
    """Runtime-only host arguments, not a replacement corpus/admission file schema.

    authorize must verify the current owner/custodian grant and exact code, policy,
    metadata and comparator refs BEFORE allowing protected reads. The comparator is
    scorer-only: it checks original failure-class/reference-binding semantics, and
    returns None when these remain unresolved. No plugin/module is loaded by name.
    """

    manifest: Manifest
    method_ref: PinnedReference
    gold_ref: PinnedReference
    index_ref: PinnedReference
    policy: Policy
    category_to_class: Mapping[str, str | None]
    source_refs: Mapping[str, SourceRef]
    comparator_ref: PinnedReference
    authorize: Callable[[], bool] | None
    compare_details: Callable[[Prediction, dict], bool | None] | None
    line_contract: str
    hash_contract: str
    parent_disposition: str

    def check(self):
        if self.authorize is None or self.compare_details is None:
            raise NeedsOwnerMetadata("current_owner_custodian_or_comparator")
        if (
            self.line_contract != "same-physical-1based-no-blanks.v1"
            or self.hash_contract != "grounded-nfc-whole-method-no-newline.v1"
            or not self.parent_disposition
            or any(
                ref.status != "available"
                for ref in (self.method_ref, self.gold_ref, self.index_ref, self.comparator_ref)
            )
            or set(v for v in self.category_to_class.values() if v is not None) != set(SUPPORTS)
            or len([v for v in self.category_to_class.values() if v is not None]) != len(SUPPORTS)
        ):
            raise NeedsOwnerMetadata("line_hash_category_refs_or_parent")
        Manifest.model_validate(self.manifest.model_dump(mode="python"))
        Policy.model_validate(self.policy.model_dump(mode="python"))
        entries = [entry for entry in self.manifest.splits if entry.split == "dev"]
        if (
            len(entries) != 1
            or entries[0].item_count != 120
            or not set(entries[0].ordered_item_ids) <= self.source_refs.keys()
            or self.manifest.comparator_config != self.comparator_ref
        ):
            raise NeedsOwnerMetadata("canonical_dev_sources_or_comparator")
        for item in entries[0].ordered_item_ids:
            ref = SourceRef.model_validate(self.source_refs[item].model_dump(mode="python"))
            if ref.sha256 is None:
                raise NeedsOwnerMetadata("original_source_reference_digest")
        if not self.authorize():
            raise NeedsOwnerMetadata("current_owner_custodian_admission")


def _read_lines(ref: PinnedReference):
    path = Path(ref.ref)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("original_file_bound")
    with path.open("rb") as stream:
        data = stream.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != ref.sha256:
        raise ValueError("original_file_hash")
    if data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("original_bom")
    lines = data.split(b"\n")
    if lines[-1:] == [b""]:
        lines.pop()  # One final line terminator is not a blank record.
    if not lines or len(lines) > 5000:
        raise ValueError("original_cardinality")
    records = []
    for line in lines:
        line = line.removesuffix(b"\r")
        if not line.strip() or b"\r" in line or len(line) > 65536:
            raise ValueError("original_physical_line")
        value = _decode(line.decode("utf-8"))
        if type(value) is not dict:
            raise ValueError("original_object_required")
        records.append(value)
    return records


class OriginalGroundingMethod:
    def __init__(self, policy: Policy):
        self.policy = policy
        self.config_sha256 = identity_hash({"version": VERSION, "policy": policy.model_dump()})

    def predict(self, public: PublicMethodInput) -> Prediction:
        try:
            wire = public.public_payload
            _public(wire)
            if (
                set(wire) != {"schema_version", "payload"}
                or wire["schema_version"] != "author-method-input.v1"
                or identity_hash(wire) != public.input_sha256
                or public.public_config_refs != (VERSION, self.config_sha256)
            ):
                raise ValueError("original_method_binding")
            payload = wire["payload"]
            if (
                type(payload) is not dict
                or set(payload) != {"task", "content", "metrics", "current_generation", "policy"}
                or payload["task"] != "grounding"
            ):
                raise ValueError("original_grounding_shape")
            content = Content.model_validate_json(canonical_bytes(payload["content"]))
            policy = Policy.model_validate_json(canonical_bytes(payload["policy"]))
            if policy != self.policy or type(payload["metrics"]) is not list:
                raise ValueError("original_policy_or_metric_array")
            metrics = tuple(
                Metric.model_validate_json(canonical_bytes(metric)) for metric in payload["metrics"]
            )
            checked = validate(
                content, SuppliedMetrics(metrics, payload["current_generation"]), policy
            )
            valid = checked.report.structural_status == "valid"
            domain = {
                "valid": valid,
                "failure_codes": [failure.code for failure in checked.report.failures],
                "resolved_keys": [
                    {"generation": m.snapshot_id, "scope": m.scope, "evidence_id": m.metric_id}
                    for m in checked.evidence
                ],
                "producer_authority": False,
            }
            status, output, issues = "ok", valid, ()
        except (ValueError, TypeError, KeyError, AttributeError):
            status, domain, output = "invalid", None, None
            issues = ("invalid_original_grounding",)
        return Prediction(
            item_id=public.item_id,
            method=METHOD,
            method_version=VERSION,
            config_sha256=self.config_sha256,
            model=None,
            origin="agent_provisional",
            status=status,
            domain_payload=domain,
            machine_output=output,
            human_effective_output=None,
            human_provenance_ref=None,
            issues=issues,
            ledger_refs=(),
            source_refs=(),
        )


class OriginalScorer:
    def __init__(self, admission: CustodianAdmission, method: OriginalGroundingMethod):
        self.admission, self.method = admission, method

    def validate_gold(self, gold):
        GoldRecord.model_validate(gold.model_dump(mode="python"))
        if (
            gold.domain_kind != VERSION
            or gold.split != "dev"
            or gold.label_source != "agent_provisional"
            or not isinstance(gold.label_payload, DomainLabels)
        ):
            raise ValueError("original_gold_projection")
        payload = gold.label_payload.payload
        if set(payload) != {"class", "expected"} or payload["class"] not in SUPPORTS:
            raise ValueError("original_gold_class")
        expected = payload["expected"]
        if (
            type(expected) is not dict
            or set(expected)
            != {"kind", "expected_valid", "expected_failure_classes", "exact_reference_bindings"}
            or expected["kind"] != "grounding"
            or type(expected["expected_valid"]) is not bool
            or any(
                type(expected[key]) is not list
                or (key == "exact_reference_bindings" and not expected[key])
                or any(type(v) is not str or not v for v in expected[key])
                for key in ("expected_failure_classes", "exact_reference_bindings")
            )
        ):
            raise ValueError("original_grounding_gold")

    def to_public_input(self, gold, view):
        _public(view.public_payload)
        if (
            view.input_sha256 != gold.input_sha256
            or identity_hash(view.public_payload) != gold.input_sha256
        ):
            raise ValueError("original_public_hash")
        return PublicMethodInput.model_validate_json(
            canonical_bytes(
                {
                    "item_id": gold.item_id,
                    "public_payload": view.public_payload,
                    "input_sha256": gold.input_sha256,
                    "public_config_refs": [VERSION, self.method.config_sha256],
                }
            )
        )

    def validate_prediction(self, prediction):
        Prediction.model_validate(prediction.model_dump(mode="python"))
        if (
            prediction.origin != "agent_provisional"
            or prediction.model is not None
            or prediction.human_effective_output is not None
            or prediction.ledger_refs
        ):
            raise ValueError("original_prediction_provenance")
        if prediction.status == "ok" and (
            type(prediction.machine_output) is not bool
            or prediction.domain_payload is None
            or prediction.domain_payload.get("producer_authority") is not False
            or prediction.domain_payload.get("valid") is not prediction.machine_output
        ):
            raise ValueError("original_prediction_shape")

    def to_outcomes(self, machine, gold, policy):
        self.validate_gold(gold)
        if machine.item_id != gold.item_id or policy != self.admission.policy:
            raise ValueError("original_scorer_identity")
        expected = gold.label_payload.payload["expected"]
        detail = None
        if machine.status == "ok":
            detail = self.admission.compare_details(machine, expected)
            if type(detail) is not bool:
                raise NeedsOwnerMetadata("failure_or_reference_comparator")
        return (
            Outcome(
                item_id=gold.item_id,
                group_id=gold.group_id,
                dataset=gold.dataset,
                split=gold.split,
                method=machine.method,
                field="validity",
                **{"class": gold.label_payload.payload["class"]},
                eligibility="eligible",
                status=machine.status,
                correct=(machine.machine_output == expected["expected_valid"] and detail)
                if machine.status == "ok"
                else None,
                predicted=machine.machine_output if machine.status == "ok" else None,
                expected=expected["expected_valid"],
                human_touched_prediction=False,
                evidence_origin=machine.origin,
                issues=machine.issues,
                ledger_refs=machine.ledger_refs,
            ),
        )

    def metric_specs(self):
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

    def public_projection_policy(self):
        return self.admission.manifest.publication_policy


def evaluate(admission: CustodianAdmission | None):
    if admission is None:
        raise NeedsOwnerMetadata("trusted_custodian_host_required")
    admission.check()  # No protected path is opened before this succeeds.
    methods = _read_lines(admission.method_ref)
    golds = _read_lines(admission.gold_ref)
    index = _read_lines(admission.index_ref)
    if not len(methods) == len(golds) == len(index) == 711:
        raise ValueError("original_same_line_cardinality")
    entries = [e for e in admission.manifest.splits if e.split == "dev"]
    if len(entries) != 1 or entries[0].item_count != 120:
        raise NeedsOwnerMetadata("canonical_dev_scope")
    groups = {
        item: group for group, items in admission.manifest.group_members.items() for item in items
    }
    seen, records, views, counts = set(), [], {}, dict.fromkeys(SUPPORTS, 0)
    for line, (method, gold, pointer) in enumerate(zip(methods, golds, index, strict=True), 1):
        if (
            set(pointer) != {"category", "fixture_id", "line_1based"}
            or set(method) != {"schema_version", "payload"}
            or method["schema_version"] != "author-method-input.v1"
            or type(method["payload"]) is not dict
            or set(gold) != _GOLD_FIELDS
            or type(pointer["line_1based"]) is not int
            or pointer["line_1based"] != line
            or type(pointer["fixture_id"]) is not str
            or not pointer["fixture_id"]
            or pointer["fixture_id"] in seen
            or pointer["fixture_id"] != gold.get("fixture_id")
            or gold.get("schema_version") != "author-gold-input.v1"
            or gold.get("split") != "dev"
            or gold.get("method_input_sha256") != identity_hash(method)
            or gold.get("label_provenance") != "agent_provisional"
            or gold.get("human_gold") is not False
            or gold.get("human_agreement_measured") is not False
            or pointer["category"] not in admission.category_to_class
            or type(gold["unknown_required_reference_count"]) is not int
            or gold["unknown_required_reference_count"] < 0
            or type(gold["what_bug_this_catches"]) is not str
            or not gold["what_bug_this_catches"]
            or any(
                type(gold[key]) is not list
                or not gold[key]
                or any(type(value) is not str or not value for value in gold[key])
                for key in ("private_source_family_ids", "required_reference_ids")
            )
            or any(
                type(gold[key]) is not list or any(type(value) is not dict for value in gold[key])
                for key in ("contentGroundReferences", "conflicts")
            )
        ):
            raise ValueError("original_physical_identity_join")
        seen.add(pointer["fixture_id"])
        category = admission.category_to_class[pointer["category"]]
        if category is None:
            continue
        if gold["unknown_required_reference_count"] or gold["conflicts"]:
            raise NeedsOwnerMetadata("original_required_reference_or_conflict")
        counts[category] += 1
        fixture_id = gold["fixture_id"]
        if fixture_id not in groups or fixture_id not in admission.source_refs:
            raise NeedsOwnerMetadata("original_group_or_source_ref")
        record = GoldRecord(
            item_id=fixture_id,
            dataset=admission.manifest.manifest_id,
            group_id=groups[fixture_id],
            split="dev",
            label_version="author-gold-input.v1",
            source_ref=admission.source_refs[fixture_id],
            input_sha256=gold["method_input_sha256"],
            label_source="agent_provisional",
            label_provenance_ref=None,
            domain_kind=VERSION,
            label_payload=DomainLabels(
                kind="domain_labels", payload={"class": category, "expected": gold.get("expected")}
            ),
        )
        records.append(record)
        views[fixture_id] = SourceView("available", record.input_sha256, method)
    if counts != SUPPORTS or tuple(r.item_id for r in records) != entries[0].ordered_item_ids:
        raise ValueError("original_declared_support_or_order")
    method = OriginalGroundingMethod(admission.policy)
    scorer = OriginalScorer(admission, method)
    admission.check()  # Current host authority is checked again before method execution.
    result = compare(
        {METHOD: MethodConfig(VERSION, method.config_sha256, "agent_provisional", method)},
        admission.manifest,
        "dev",
        tuple(records),
        scorer,
        admission.policy,
        lambda gold: views[gold.item_id],
    )
    outcomes = result.methods[METHOD].outcomes
    rows = []
    for category in SUPPORTS:
        selected = tuple(o for o in outcomes if o.class_name == category)
        ids = tuple(r.item_id for r in records if r.label_payload.payload["class"] == category)
        rows.append(
            metric_row(
                selected,
                ids,
                scorer.metric_specs()[0],
                accuracy,
                method=METHOD,
                dataset_alias="original-dev-grounding",
                split="dev",
                config_ref=method.config_sha256,
                field="validity",
                class_name=category,
            )
        )
    return outcomes, tuple(rows)


def main(argv=None, *, admission: CustodianAdmission | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("replay",), required=True)
    parser.add_argument("--split", choices=("dev",), required=True)
    parser.parse_args(argv)
    try:
        outcomes, rows = evaluate(admission)
    except NeedsOwnerMetadata as error:
        print(
            json.dumps(
                {
                    "status": "needs_owner_metadata",
                    "reason": str(error),
                    "campaign_qualified": False,
                    "selected_required_N": 120,
                }
            )
        )
        return 2
    except (ValueError, OSError, TypeError, KeyError):
        print(
            json.dumps(
                {"status": "refused", "reason": "original_wire_admission", "measured": False}
            )
        )
        return 1
    passed = all(row.value == 1 and row.denominator == SUPPORTS[row.class_name] for row in rows)
    print(
        json.dumps(
            {
                "status": "pass" if passed else "fail",
                "selected_N": len(outcomes),
                "unselected_not_run": 591,
                "producer_authority": False,
                "model_quality_measured": False,
                "floors": [
                    {
                        "class": row.class_name,
                        "numerator": row.numerator,
                        "denominator": row.denominator,
                    }
                    for row in rows
                ],
            }
        )
    )
    return 0 if passed else 1
