"""Report contracts-only status without starting a service or workflow."""

import argparse
import json

from content_strategy import __version__


def main(argv: list[str] | None = None) -> int:
    """Expose only help, version and explicit unfinished status."""
    parser = argparse.ArgumentParser(
        description="Content Strategy Agent: structural contracts only."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--status-json", action="store_true", help="Report the implementation stage."
    )
    arguments = parser.parse_args(argv)
    if arguments.status_json:
        print(
            json.dumps(
                {
                    "stage": "contracts-only",
                    "version": __version__,
                    "implemented_workflows": [],
                    "implemented_components": ["grounded_structural_models", "canonical_identity"],
                    "schema_validation_is_authorization": False,
                    "provider_calls": False,
                    "approval_export_available": False,
                },
                sort_keys=True,
            )
        )
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
