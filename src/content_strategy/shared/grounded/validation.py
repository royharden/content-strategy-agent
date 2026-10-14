"""Bounded, explicit claim grammar and exact evidence checks; no NLP or provider authority."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field

from .identity import canonical_decimal, identity_hash
from .models import (
    Digest,
    EvidenceKey,
    GroundedItem,
    Identifier,
    Metric,
    Record,
    Text,
    ValidationFailure,
    ValidationReport,
)

VALIDATOR_VERSION = "grounded-validator.v1"
TOKEN = re.compile(r"\{\{(cite|edit):([^{}\n]+)\}\}")
NUMBER_WORDS = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
    "eighty ninety hundred thousand million billion trillion dozen half quarter double "
    "triple twice thrice twofold threefold tenfold percent percentage multiplier".split()
)


class Policy(Record):
    edition: Identifier = "grounded-policy.v1"
    validator_version: Literal["grounded-validator.v1"] = VALIDATOR_VERSION
    screen_edition: Identifier
    minimum_sample: int = Field(default=5, ge=1, le=100000)
    max_bundle_items: int = Field(default=100, ge=1, le=1000)

    @property
    def digest(self) -> str:
        return identity_hash(self.model_dump(mode="python"))


class EditorialLiteral(Record):
    name: Identifier
    role: Literal["count", "cadence", "horizon"]
    value: int = Field(ge=1, le=90)

    def render(self) -> str:
        # The entire token must occupy a line. No arbitrary performance-claim substitution.
        label = {
            "count": "Proposed item count",
            "cadence": "Proposed weekly item count",
            "horizon": "Proposed horizon in days",
        }[self.role]
        return f"{label}: {self.value} (editorial choice)"


class PassageEvidence(Record):
    key: EvidenceKey
    excerpt: Text
    status: Literal["ok", "unavailable"]


class PassageCitation(Record):
    key: EvidenceKey
    quoted_text: Text


class Content(Record):
    item: GroundedItem
    editorial: tuple[EditorialLiteral, ...] = ()
    passages: tuple[PassageCitation, ...] = ()


class Assessment(Record):
    content_hash: Digest
    evidence_hash: Digest
    policy_hash: Digest
    screen_edition: Identifier
    screen_status: Literal["pass", "hold", "not_run"]
    semantic_status: Literal["supports", "contradicts", "says_nothing", "unknown", "not_run"]


class CurrentEvidence(Protocol):
    def current_generation(self, scope: str) -> str | None: ...
    def resolve(self, key: EvidenceKey) -> Metric | PassageEvidence | None: ...


def content_hash(
    item: GroundedItem,
    editorial: tuple[EditorialLiteral, ...] = (),
    passages: tuple[PassageCitation, ...] = (),
) -> str:
    return identity_hash(
        {
            "item": item.model_dump(mode="python", exclude={"content_hash"}),
            "editorial": [value.model_dump(mode="python") for value in editorial],
            "passages": [value.model_dump(mode="python") for value in passages],
        }
    )


def seal_content(
    *,
    editorial: tuple[EditorialLiteral, ...] = (),
    passages: tuple[PassageCitation, ...] = (),
    **item_fields,
) -> Content:
    """Hash a proposed version. Sealing confers no validation, approval or human identity."""
    item = GroundedItem(**item_fields, content_hash="0" * 64)
    return Content(
        item=GroundedItem(**item_fields, content_hash=content_hash(item, editorial, passages)),
        editorial=editorial,
        passages=passages,
    )


@dataclass(frozen=True)
class Checked:
    content: Content
    report: ValidationReport
    rendered: str
    evidence_hash: str
    evidence: tuple[Metric | PassageEvidence, ...]


def validate(content: Content, resolver: CurrentEvidence, policy: Policy) -> Checked:
    # Revalidate dumps, including nested records, rather than accepting model_copy bypasses.
    content = Content.model_validate(content.model_dump(mode="python"))
    policy = Policy.model_validate(policy.model_dump(mode="python"))
    item = content.item
    failures = []

    def fail(code, reference=None):
        failures.append(ValidationFailure(code=code, reference_id=reference))

    if item.content_hash != content_hash(item, content.editorial, content.passages):
        fail("content_hash_mismatch")
    if resolver.current_generation(item.scope) != item.snapshot_id:
        fail("stale_or_inaccessible_generation")
    if item.kind not in {"recommendation", "draft"}:
        fail("unsupported_item_kind")
    if (item.kind == "draft") != (item.parent_id is not None):
        fail("invalid_parent_shape")
    citations = {}
    evidence = []
    if not item.citations and not content.passages:
        fail("missing_citations")
    for citation in item.citations:
        if citation.metric_id in citations:
            fail("duplicate_or_conflicting_citation", citation.metric_id)
            continue
        citations[citation.metric_id] = citation
        if citation.snapshot_id != item.snapshot_id or citation.scope != item.scope:
            fail("citation_generation_or_scope", citation.metric_id)
            continue
        metric = resolver.resolve(citation.key)
        if metric is None:
            fail("unknown_or_inaccessible_evidence", citation.metric_id)
            continue
        if not isinstance(metric, Metric):
            fail("evidence_type_mismatch", citation.metric_id)
            continue
        metric = Metric.model_validate(metric.model_dump(mode="python"))
        evidence.append(metric)
        if (metric.metric_id, metric.snapshot_id, metric.scope) != (
            citation.metric_id,
            item.snapshot_id,
            item.scope,
        ):
            fail("resolver_key_mismatch", citation.metric_id)
        if (
            metric.status != "ok"
            or metric.sample_size < policy.minimum_sample
            or metric.value is None
        ):
            fail("uncitable_evidence", citation.metric_id)
        if metric.value != citation.quoted_value or metric.unit != citation.unit:
            fail("noncanonical_value_or_unit", citation.metric_id)

    for citation in content.passages:
        key = citation.key
        if key.evidence_id in citations:
            fail("duplicate_or_conflicting_citation", key.evidence_id)
            continue
        citations[key.evidence_id] = citation
        if key.generation != item.snapshot_id or key.scope != item.scope:
            fail("citation_generation_or_scope", key.evidence_id)
            continue
        passage = resolver.resolve(key)
        if not isinstance(passage, PassageEvidence):
            fail("unknown_or_inaccessible_evidence", key.evidence_id)
            continue
        passage = PassageEvidence.model_validate(passage.model_dump(mode="python"))
        evidence.append(passage)
        if passage.key != key:
            fail("resolver_key_mismatch", key.evidence_id)
        if passage.status != "ok":
            fail("uncitable_evidence", key.evidence_id)
        if passage.excerpt != citation.quoted_text:
            fail("noncanonical_passage_quote", key.evidence_id)

    literals = {value.name: value for value in content.editorial}
    if len(literals) != len(content.editorial):
        fail("duplicate_editorial_literal")
    used_citations, used_editorial = set(), set()

    def replace_token(match):
        kind, key = match.groups()
        if kind == "cite":
            if key not in citations:
                fail("unknown_placeholder", key)
                return ""
            used_citations.add(key)
            cited = citations[key]
            if isinstance(cited, PassageCitation):
                return cited.quoted_text
            return canonical_decimal(cited.quoted_value) + " " + cited.unit
        literal = literals.get(key)
        line = item.text[
            item.text.rfind("\n", 0, match.start()) + 1 : item.text.find("\n", match.end())
            if "\n" in item.text[match.end() :]
            else len(item.text)
        ]
        if literal is None or line.strip() != match.group(0):
            fail("invalid_editorial_role", key)
            return ""
        used_editorial.add(key)
        return literal.render()

    parts, cursor, rendered_bytes = [], 0, 0
    for match in TOKEN.finditer(item.text):
        segment = item.text[cursor : match.start()] + replace_token(match)
        rendered_bytes += len(segment.encode("utf-8"))
        if rendered_bytes > 2 * 1024 * 1024:
            fail("render_byte_limit")
            parts = []
            cursor = len(item.text)
            break
        parts.append(segment)
        cursor = match.end()
    suffix = item.text[cursor:]
    if rendered_bytes + len(suffix.encode("utf-8")) > 2 * 1024 * 1024:
        fail("render_byte_limit")
        rendered = ""
    else:
        rendered = "".join(parts) + suffix
    residue = TOKEN.sub("", item.text)
    normalized = unicodedata.normalize("NFKC", residue).casefold()
    if (
        any(character.isnumeric() for character in residue + normalized)
        or NUMBER_WORDS.intersection(re.findall(r"[^\W\d_]+", normalized))
        or any(symbol in normalized for symbol in ("%", "‰", "{{", "}}"))
    ):
        fail("unsupported_numeric_grammar")
    if used_citations != set(citations):
        fail("unused_citation")
    if used_editorial != set(literals):
        fail("unused_editorial_literal")
    evidence = tuple(
        sorted(
            evidence,
            key=lambda value: (
                value.metric_id if isinstance(value, Metric) else value.key.evidence_id
            ),
        )
    )
    report = ValidationReport(
        item_id=item.item_id,
        revision=item.revision,
        snapshot_id=item.snapshot_id,
        structural_status="invalid" if failures else "valid",
        failures=tuple(failures),
        semantic_status="not_run",
        validator_version=policy.validator_version,
    )
    return Checked(
        content,
        report,
        "" if failures else rendered,
        identity_hash([metric.model_dump(mode="python") for metric in evidence]),
        evidence,
    )
