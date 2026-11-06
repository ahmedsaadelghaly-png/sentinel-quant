"""Alerts. Failing to send one is logged and never stops trading logic."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from sentinel_quant.config.secrets import Secrets
from sentinel_quant.ops.logging import get_logger

_TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT_SECONDS = 10
_MAX_MESSAGE = 4000  # Telegram's limit is 4096 characters


class LogNotifier:
    def send(self, level: str, message: str) -> None:
        get_logger().info("alert", level=level, message=message)


class TelegramNotifier:
    """Official Bot API. Everything is also written to the log."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._url = _TELEGRAM_URL.format(token=token)
        self._chat_id = chat_id
        self._fallback = LogNotifier()

    def send(self, level: str, message: str) -> None:
        self._fallback.send(level, message)
        text = f"[{level.upper()}] {message}"[:_MAX_MESSAGE]
        body = json.dumps({"chat_id": self._chat_id, "text": text}).encode()
        request = urllib.request.Request(  # noqa: S310
            self._url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS):  # noqa: S310
                pass
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # The exception text can contain the URL, and the URL contains the token.
            get_logger().warning("alert_not_delivered", error=type(exc).__name__)


def build_notifier(enabled: bool, secrets: Secrets) -> LogNotifier | TelegramNotifier:
    if not enabled:
        return LogNotifier()
    token, chat = secrets.telegram_bot_token, secrets.telegram_chat_id
    if token is None or chat is None:
        raise ValueError(
            "alerts.telegram_enabled needs SQ_TELEGRAM_BOT_TOKEN and SQ_TELEGRAM_CHAT_ID"
        )
    return TelegramNotifier(token.get_secret_value(), chat.get_secret_value())
