"""Notification backends for N+1 detection results.

LogNotifier logs messages; ErrorNotifier raises exceptions.
"""

import logging
from typing import Any

from nplusone.core import exceptions
from nplusone.core.listeners import Message


class Notifier:
    """Base class for notification backends."""

    CONFIG_KEY: str = ""
    ENABLED_DEFAULT: bool = False

    @classmethod
    def is_enabled(cls, config: dict[str, Any]) -> bool:
        """Check if this notifier is enabled in the given config."""
        if not cls.CONFIG_KEY:
            return cls.ENABLED_DEFAULT
        return bool(
            config.get(cls.CONFIG_KEY)
            or (cls.CONFIG_KEY not in config and cls.ENABLED_DEFAULT)
        )

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def notify(self, message: Message) -> None:
        """Send a notification for the given detection message."""


class LogNotifier(Notifier):
    """Logs detection messages to a Python logger."""

    CONFIG_KEY = "NPLUSONE_LOG"
    ENABLED_DEFAULT = True

    def __init__(self, config: dict[str, Any]) -> None:
        self.logger: logging.Logger = config.get(
            "NPLUSONE_LOGGER", logging.getLogger("nplusone")
        )
        self.level: int = config.get("NPLUSONE_LOG_LEVEL", logging.DEBUG)

    def notify(self, message: Message) -> None:
        """Log the detection message."""
        self.logger.log(self.level, message.message)


class ErrorNotifier(Notifier):
    """Raises exceptions on detection."""

    CONFIG_KEY = "NPLUSONE_RAISE"
    ENABLED_DEFAULT = False

    def __init__(self, config: dict[str, Any]) -> None:
        self.error: type[Exception] = config.get(
            "NPLUSONE_ERROR", exceptions.NPlusOneError
        )

    def notify(self, message: Message) -> None:
        """Raise an exception with the detection message."""
        raise self.error(message.message)


def init(config: dict[str, Any]) -> list[Notifier]:
    """Initialize enabled notifiers from configuration."""
    return [
        notifier(config)
        for notifier in (LogNotifier, ErrorNotifier)
        if notifier.is_enabled(config)
    ]
