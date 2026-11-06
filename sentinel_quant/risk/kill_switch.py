"""Independent kill switch: a file any operator or process can create.

The flag lives outside the bot's memory, so it survives restarts and works even if
the trading process is misbehaving. Strategy and AI code have no reason to touch it;
release is an operator action (``sentinel-quant kill-switch off``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


class KillSwitch:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()  # one absolute file, whatever the working directory

    def engaged(self) -> bool:
        """True if engaged, or if the flag cannot be read: unknown means stop."""
        try:
            self.path.stat()
        except FileNotFoundError:
            return False
        except OSError:
            return True
        return True

    def engage(self, reason: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).isoformat()
        self.path.write_text(f"{stamp} {reason}\n", encoding="utf-8")

    def release(self) -> None:
        self.path.unlink(missing_ok=True)
