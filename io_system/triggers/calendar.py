"""Calendar-driven trigger.

Wraps the existing :class:`CalendarMonitor` (EventKit + PyObjC) and re-emits
its ``CalendarEventChange`` observations as the generic ``TriggerEvent``
format. Behavior matches the legacy ``CalendarMonitor`` exactly: the same
PyObjC run loop, the same access prompt, the same 48-hour default window.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from io_system.context_engine.calendar_monitor import (
    CalendarEventChange,
    CalendarMonitor,
)

from .base import EventTrigger, TriggerCallback, TriggerEvent


class CalendarEventTrigger(EventTrigger):
    """Bridges :class:`CalendarMonitor` to the generic trigger interface."""

    name = "calendar"

    def __init__(
        self,
        on_event: TriggerCallback,
        watch_window_days: int = 2,
        emit_initial_snapshot: bool = False,
    ):
        super().__init__(on_event)
        self.watch_window_days = watch_window_days
        self.emit_initial_snapshot = emit_initial_snapshot
        self._monitor: Optional[CalendarMonitor] = None

    @classmethod
    def is_available(cls) -> bool:
        return CalendarMonitor.is_available()

    def start(self) -> None:
        if not self.is_available():
            return
        if self._monitor is not None:
            return
        self._monitor = CalendarMonitor(
            on_event_changed=self._handle_change,
            watch_window_days=self.watch_window_days,
            emit_initial_snapshot=self.emit_initial_snapshot,
        )
        self._monitor.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._monitor is not None:
            self._monitor.stop(timeout=timeout)
            self._monitor = None

    # ----- internal -----

    def _handle_change(self, change: CalendarEventChange) -> None:
        ts = change.start or datetime.now(timezone.utc)
        content = (
            f"Calendar event: '{change.title}' "
            f"{change.start} to {change.end}. {change.notes}"
        ).strip()
        event = TriggerEvent(
            source=self.name,
            title=change.title,
            content=content,
            timestamp=ts,
            metadata={
                "start": change.start.isoformat() if change.start else None,
                "end": change.end.isoformat() if change.end else None,
                "calendar": change.calendar,
                "is_new": change.is_new,
                "notes": change.notes,
            },
            event_id=change.event_id,
        )
        self._emit(event)
