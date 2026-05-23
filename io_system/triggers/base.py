"""Base abstractions for external event triggers.

A trigger is any external signal that should wake the agent. Each trigger
runs in its own background thread, owns whatever connection or watcher it
needs, and emits a uniform ``TriggerEvent`` to the supplied callback. The
agent layer then decides whether to react (e.g., schedule a proactive
check-in).

Design notes:
    * Triggers degrade gracefully. ``is_available()`` returns False when the
      underlying capability is missing (e.g., EventKit on Linux), and
      ``start()`` becomes a no-op rather than raising.
    * The callback is invoked from the trigger's own thread. Keep handlers
      cheap or hand work off to a queue.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional


@dataclass
class TriggerEvent:
    """A single observation from any source, normalized for the agent."""

    source: str
    title: str
    content: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    event_id: Optional[str] = None


TriggerCallback = Callable[[TriggerEvent], None]


class EventTrigger(ABC):
    """Abstract external trigger.

    Subclasses must define a class-level ``name`` (e.g., ``"calendar"``),
    implement ``is_available()`` to declare whether they can run in the
    current environment, and implement ``start()``/``stop()`` to manage
    their own background work.
    """

    name: str = "trigger"

    def __init__(self, on_event: TriggerCallback):
        self.on_event = on_event

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Whether this trigger can run in the current environment."""

    @abstractmethod
    def start(self) -> None:
        """Begin emitting events. Should be idempotent."""

    @abstractmethod
    def stop(self, timeout: float = 5.0) -> None:
        """Stop emitting events. Should be idempotent."""

    # ----- helpers for subclasses -----

    def _emit(self, event: TriggerEvent) -> None:
        """Dispatch an event to the registered callback, swallowing errors."""
        try:
            self.on_event(event)
        except Exception:
            import logging
            logging.getLogger(self.__class__.__module__).exception(
                "%s: on_event raised", self.__class__.__name__
            )
