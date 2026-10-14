"""Generate structural schemas for runtime additions; this never certifies authority."""

import argparse
import json
from pathlib import Path

from content_strategy.shared.grounded.audit import ExportRequest
from content_strategy.shared.grounded.validation import (
    Assessment,
    Content,
    EditorialLiteral,
    PassageCitation,
    PassageEvidence,
    Policy,
)


def document():
    models = (
        Assessment,
        Content,
        EditorialLiteral,
        PassageCitation,
        PassageEvidence,
        Policy,
        ExportRequest,
    )
    return {
        "schema_version": 1,
        "edition": "grounded-runtime.v1",
        "structural_only": True,
        "models": {
            model.__name__: model.model_json_schema(mode="serialization") for model in models
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).with_name("grounded-runtime-v1.schema.json")
    rendered = json.dumps(document(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.check:
        raise SystemExit(0 if target.read_text(encoding="utf-8") == rendered else 1)
    target.write_text(rendered, encoding="utf-8", newline="\n")
