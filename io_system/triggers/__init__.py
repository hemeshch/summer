"""External event triggers that wake the agent.

A ``EventTrigger`` is anything that observes the outside world (calendar
events, new email, an HTTP push, a file landing in a watched directory) and
emits a uniform ``TriggerEvent`` for the agent to react to. The main
pipeline registers any available triggers and routes their events through a
single bridge function.
"""

from .base import EventTrigger, TriggerCallback, TriggerEvent
from .bridge import (
    CALENDAR_MIN_DURATION,
    CALENDAR_WAKE_HORIZON,
    CALENDAR_WAKE_SENTINEL,
    TRIGGER_WAKE_SENTINEL,
    on_trigger_event,
)
from .calendar import CalendarEventTrigger
from .email import EmailTrigger
from .file_watcher import FileWatcherTrigger
from .webhook import WebhookTrigger

__all__ = [
    "EventTrigger",
    "TriggerCallback",
    "TriggerEvent",
    "CalendarEventTrigger",
    "EmailTrigger",
    "WebhookTrigger",
    "FileWatcherTrigger",
    "on_trigger_event",
    "CALENDAR_WAKE_SENTINEL",
    "TRIGGER_WAKE_SENTINEL",
    "CALENDAR_WAKE_HORIZON",
    "CALENDAR_MIN_DURATION",
]
