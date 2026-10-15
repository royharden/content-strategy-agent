"""Command-line entrypoint; import creates no runtime resources."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
