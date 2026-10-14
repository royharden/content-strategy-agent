from decimal import Decimal

import pytest

from content_strategy.shared.grounded.validation import Content, EditorialLiteral, validate


def codes(content, fixture):
    return {
        failure.code
        for failure in validate(content, fixture.resolver, fixture.policy).report.failures
    }


def test_positive_exact_numeric_render_with_explicit_editorial_role(harness):
    h = harness()
    content = h.content(
        text="Evidence {{cite:fact}}\n{{edit:cadence}}",
        editorial=(EditorialLiteral(name="cadence", role="cadence", value=3),),
    )
    checked = validate(content, h.resolver, h.policy)
    assert (
        checked.report.structural_status == "valid" and checked.report.semantic_status == "not_run"
    )
    assert (
        checked.rendered == "Evidence 0.125 ratio\nProposed weekly item count: 3 (editorial choice)"
    )


@pytest.mark.parametrize(
    "claim",
    [
        "10%",
        "０.１２５",
        "Ⅻ",
        "½",
        "ten",
        "one-hundred",
        "double",
        "twofold",
        "1e2",
        "2–3",
        "3x",
        "{{other:fact}}",
    ],
)
def test_numeric_grammar_unsupported_claims_reject(harness, claim):
    h = harness()
    assert "unsupported_numeric_grammar" in codes(h.content(text="{{cite:fact}} " + claim), h)


def test_finite_grammar_boundary_does_not_claim_universal_nlp(harness):
    h = harness()
    # Semantic review must handle words beyond the named grammar, rather than universal claims.
    assert not codes(h.content(text="Evidence {{cite:fact}} improved considerably"), h)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"quoted_value": "0.13"}, "noncanonical_value_or_unit"),
        ({"quoted_value": "0.12500001"}, "noncanonical_value_or_unit"),
        ({"unit": "percent"}, "noncanonical_value_or_unit"),
        ({"scope": "other"}, "citation_generation_or_scope"),
        ({"snapshot_id": "b" * 64}, "citation_generation_or_scope"),
        ({"metric_id": "absent"}, "unknown_or_inaccessible_evidence"),
    ],
)
def test_citation_wrong_value_unit_scope_generation_and_missing(harness, change, code):
    h = harness()
    original = h.content().item.citations[0]
    citation = type(original).model_validate(original.model_dump() | change)
    assert code in codes(h.content(citations=(citation,)), h)


def test_missing_duplicate_unused_placeholder_and_stale_generation(harness):
    h = harness()
    assert "missing_citations" in codes(h.content(citations=()), h)
    citation = h.content().item.citations[0]
    assert "duplicate_or_conflicting_citation" in codes(
        h.content(citations=(citation, citation)), h
    )
    assert "unused_citation" in codes(h.content(text="A proposed direction"), h)
    assert "unknown_placeholder" in codes(h.content(text="{{cite:unknown}}"), h)
    h.resolver.generation = "b" * 64
    assert "stale_or_inaccessible_generation" in codes(h.content(), h)


@pytest.mark.parametrize(
    "change",
    [
        {"sample_size": 4},
        {"status": "insufficient_data", "status_reason": "n_low"},
        {"status": "unavailable", "status_reason": "missing", "value": None},
    ],
)
def test_uncitable_sample_status_and_absent_value(harness, change):
    h = harness()
    h.resolver.metrics["fact"] = type(h.metric).model_validate(h.metric.model_dump() | change)
    assert "uncitable_evidence" in codes(h.content(), h)


def test_resolver_wrong_key_and_content_hash_bypass_caught(harness):
    h = harness()
    h.resolver.metrics["fact"] = type(h.metric).model_validate(
        h.metric.model_dump() | {"metric_id": "wrong"}
    )
    assert "resolver_key_mismatch" in codes(h.content(), h)
    content = h.content()
    altered = Content(item=content.item.model_copy(update={"text": "tampered {{cite:fact}}"}))
    assert "content_hash_mismatch" in codes(altered, h)


def test_typed_editorial_values_not_free_form_performance_injection(harness):
    h = harness()
    literal = EditorialLiteral(name="choice", role="count", value=2)
    assert "invalid_editorial_role" in codes(
        h.content(text="Performance {{edit:choice}} {{cite:fact}}", editorial=(literal,)), h
    )
    assert "unused_editorial_literal" in codes(h.content(editorial=(literal,)), h)
    with pytest.raises(ValueError):
        EditorialLiteral(name="x", role="count", value=True)
    with pytest.raises(ValueError):
        h.content().item.citations[0].model_validate(
            h.content().item.citations[0].model_dump() | {"quoted_value": Decimal("NaN")}
        )
