"""DEV original grounding entrypoint; a trusted custodian host must inject admission.

Ordinary shell use refuses before corpus IO while actual owner metadata remains
unresolved. This entrypoint does not auto-discover data or load executable plugins.
"""

from content_strategy.evaluation.original_grounding import main

if __name__ == "__main__":
    raise SystemExit(main())
