"""Secrets come only from environment variables (or a local, git-ignored .env).

They are never stored in YAML configs and never printed or logged.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SQ_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    exchange_api_key: SecretStr | None = None
    exchange_api_secret: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: SecretStr | None = None

    def has_exchange_keys(self) -> bool:
        return self.exchange_api_key is not None and self.exchange_api_secret is not None

    def all_values(self) -> list[str]:
        """Plain values of every set secret, for log redaction only."""
        out: list[str] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr):
                raw = value.get_secret_value()
                if raw:
                    out.append(raw)
        return out
