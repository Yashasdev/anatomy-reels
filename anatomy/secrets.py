"""Read secrets from the environment (GitHub passes the repo secrets under these names)."""

from __future__ import annotations

import os


def env(name: str) -> str:
    """A secret pasted into GitHub often carries a trailing newline or space; HTTP headers reject those."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"the {name} secret is missing or empty")
    return value
