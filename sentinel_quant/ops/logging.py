"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable, MutableMapping
from typing import Any

import structlog

REDACTED = "***REDACTED***"


class SecretRedactor:
    """structlog processor that replaces any known secret value in log events."""

    def __init__(self, secrets: Iterable[str]) -> None:
        self._secrets = [s for s in secrets if s and len(s) >= 4]

    def _scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            for s in self._secrets:
                if s in value:
                    value = value.replace(s, REDACTED)
            return value
        if isinstance(value, dict):
            return {k: self._scrub(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return type(value)(self._scrub(v) for v in value)
        return value

    def __call__(
        self, _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        for k in list(event_dict):
            event_dict[k] = self._scrub(event_dict[k])
        return event_dict


def configure_logging(secrets: Iterable[str] = (), level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            SecretRedactor(secrets),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str = "sentinel_quant") -> Any:
    return structlog.get_logger(name)
