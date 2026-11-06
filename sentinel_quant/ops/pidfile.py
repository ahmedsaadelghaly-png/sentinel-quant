"""One service per ledger: two processes trading the same book would corrupt it."""

from __future__ import annotations

import os
from pathlib import Path


def running_pid(path: Path) -> int | None:
    """The live process recorded in ``path``, or None if there is none."""
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid  # alive, owned by someone else
    return pid


def acquire_pid(path: Path) -> bool:
    if running_pid(path) is not None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_pid(path: Path) -> None:
    path.unlink(missing_ok=True)
