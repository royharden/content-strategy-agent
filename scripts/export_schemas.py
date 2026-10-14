"""Generate deterministic structural schemas; a schema is not an authorization check."""

import argparse
import json
from pathlib import Path

from content_strategy.shared.grounded import PUBLIC_MODELS


def render_schemas() -> str:
    bundle = {
        "edition": "grounded-models.v1",
        "scope": "structural-only; no evidence, approval or export authorization",
        "models": {model.__name__: model.model_json_schema() for model in PUBLIC_MODELS},
    }
    return json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "schemas/grounded-v1.json",
    )
    arguments = parser.parse_args()
    expected = render_schemas()
    if arguments.check:
        if not arguments.output.is_file() or arguments.output.read_bytes() != expected.encode(
            "utf-8"
        ):
            parser.exit(1, "Generated structural schemas are missing or changed\n")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_bytes(expected.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
