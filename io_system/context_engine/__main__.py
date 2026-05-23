"""Allow `python -m io_system.context_engine ...`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
