import json
from dataclasses import replace
from decimal import Decimal

import pytest

from content_strategy.ingest import Dataset
from content_strategy.pipeline.ports import Bindings, TagChoice, TagResult
from content_strategy.tagging import tag_dataset


def dataset(h, **changes):
    return Dataset((replace(h.dataset.rows[0], **changes),), "0" * 64)


def test_supplied_tags_preserved_keyword_and_untagged_paths_keep_every_field(harness):
    h = harness
    source = dataset(h, topic="My Custom Topic", text="launch a feature?")
    run = tag_dataset(source, method="keyword")
    assert len(run.provenance) == 2
    assert run.provenance[0].value == "My Custom Topic" and run.provenance[0].method == "supplied"
    assert run.provenance[1].value == "question"
    unknown = tag_dataset(dataset(h, text="A quiet note"), method="untagged")
    assert all(tag.value == "untagged" for tag in unknown.provenance) and len(unknown.reasons) == 2
    keyword = tag_dataset(dataset(h, text="Learn using this guide"), method="keyword")
    assert keyword.provenance[0].value == "education"
    ambiguous = tag_dataset(dataset(h, text="Learn about our release"), method="keyword")
    assert ambiguous.provenance[0].value == "untagged"


class Tagger:
    def __init__(self, confidence="0.9"):
        self.calls = []
        self.confidence = confidence

    def classify(self, assembly, *, binding):
        self.calls.append((assembly, binding))
        return TagResult(
            topic=TagChoice(value="product", confidence=self.confidence),
            format=TagChoice(value="text", confidence="0.99"),
            method="jev",
            model_reported="authored-typed-fixture",
        )


def test_probability_projection_preserves_precision_separate_from_metric_wire():
    choice = TagChoice(value="product", confidence="0.91234567890123456789")
    assert choice.confidence == Decimal("0.91234567890123456789")
    assert TagChoice(value="product", confidence=0.91).confidence == Decimal("0.91")
    for value in (True, float("nan"), float("inf"), -0.01, 1.01):
        with pytest.raises(ValueError):
            TagChoice(value="product", confidence=value)


def test_typed_minimal_screened_payload_threshold_and_model_provenance(harness):
    h = harness
    source = dataset(h, text="Release note", topic=None, format=None)
    tagger = Tagger("0.89")
    bindings = h.bindings(generation=source.fingerprint, tag_count=1)
    run = tag_dataset(
        source,
        method="jev",
        pipeline=h.port,
        tagger=tagger,
        bindings=bindings,
        threshold=Decimal("0.9"),
    )
    assert run.provenance[0].value == "untagged" and run.provenance[1].value == "text"
    assert run.provenance[0].threshold == Decimal("0.9")
    assert run.provenance[1].model == "authored-typed-fixture"
    payload = json.loads(tagger.calls[0][0].text)
    assert set(payload) == {"text", "taxonomy"} and payload["text"] == "Release note"
    assert tagger.calls[0][1] is bindings.get("tag.0", source.fingerprint, h.policy)


def test_held_tag_input_prevents_tagger_and_preserves_supplied(harness):
    h = harness
    source = dataset(h, topic="Supplied")
    h.screen_overrides = {"deterministic_flags": ("bot_instruction",)}
    tagger = Tagger()
    run = tag_dataset(
        source,
        method="jev",
        pipeline=h.port,
        tagger=tagger,
        bindings=h.bindings(generation=source.fingerprint, tag_count=1),
        threshold=Decimal("0.9"),
    )
    assert not tagger.calls
    assert run.provenance[0].value == "Supplied" and run.provenance[1].value == "untagged"
    assert run.reasons


def test_missing_future_tag_binding_prevents_all_tag_dispatches(harness):
    h = harness
    source = Dataset(h.dataset.rows[:2], "0" * 64)
    original = h.bindings(generation=source.fingerprint, tag_count=2)
    stages = dict(original._stages)
    del stages["tag.1"]
    tagger = Tagger()
    run = tag_dataset(
        source,
        method="jev",
        pipeline=h.port,
        tagger=tagger,
        bindings=Bindings(stages),
        threshold=Decimal("0.9"),
    )
    assert not h.screen_calls and not tagger.calls and len(run.provenance) == 4


@pytest.mark.parametrize(
    "threshold", [None, 0.9, Decimal("NaN"), Decimal("1.1"), Decimal("0.123456789")]
)
def test_typed_threshold_is_explicit_exact_bounded_configuration(harness, threshold):
    with pytest.raises(ValueError):
        tag_dataset(harness.dataset, method="jev", threshold=threshold)
