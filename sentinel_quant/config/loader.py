"""Load and validate configuration from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sentinel_quant.config.schema import AppConfig

DEFAULT_CONFIG = Path("configs/default.yaml")

_SECRET_HINTS = ("key", "secret", "token", "password")


class ConfigError(ValueError):
    pass


def _reject_secrets(node: Any, path: str = "") -> None:
    """Refuse configs that look like they contain credentials."""
    if isinstance(node, dict):
        for k, v in node.items():
            key = str(k).lower()
            if any(h in key for h in _SECRET_HINTS) and v not in (None, ""):
                raise ConfigError(
                    f"'{path}{k}' looks like a secret. Put secrets in environment "
                    "variables (SQ_*), never in config files."
                )
            _reject_secrets(v, f"{path}{k}.")


def load_config(path: str | Path = DEFAULT_CONFIG) -> AppConfig:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"config file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    _reject_secrets(raw)
    return AppConfig.model_validate(raw)
