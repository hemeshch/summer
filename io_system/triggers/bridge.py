"""Generic bridge from TriggerEvent to a scheduled proactive check-in.

This module is intentionally light. It depends only on the proactive
scheduler and the fact store, so the smoke test can exercise it without
pulling in the heavier ``main_agentic`` runtime (anthropic, websockets,
sentence-transformers, etc.).

The pipeline is:

    1. Apply per-source filters (e.g., skip short calendar events).
    2. Query the semantic fact store for relevant context.
    3. Pick a fire-time based on the event (calendar uses event start
       minus a lead; everything else fires effectively immediately).
    4. Schedule a check-in whose context bundles the event + the retrieved
       facts so the agent later wakes up with full context.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .base import TriggerEvent

if TYPE_CHECKING:
    from io_system.context_engine import FactStore
    from io_system.proactive.scheduler import ProactiveScheduler


# Sentinels for scheduled rows. The agent never produces these organically.
CALENDAR_WAKE_SENTINEL = "__SUMMER_CALENDAR_WAKE__"
TRIGGER_WAKE_SENTINEL = "__SUMMER_TRIGGER_WAKE__"

# How long an event must start within to be worth waking the agent.
CALENDAR_WAKE_HORIZON = timedelta(hours=36)
# Skip events shorter than this. Brief meetings rarely need a heads-up.
CALENDAR_MIN_DURATION = timedelta(minutes=20)

# LRU-style cap on the in-memory event-id dedupe set. Bounded so a long-lived
# process doesn't grow this set unboundedly when triggers fire frequently.
_SEEN_IDS_MAX = 4096
_seen_ids: "OrderedDict[str, None]" = OrderedDict()
_seen_ids_lock = threading.Lock()


def _seen_recently(event_id: str) -> bool:
    """Return True if we've already routed this event_id in the current process.

    Trims the LRU when it grows past ``_SEEN_IDS_MAX``. Thread-safe.
    """
    with _seen_ids_lock:
        if event_id in _seen_ids:
            _seen_ids.move_to_end(event_id)
            return True
        _seen_ids[event_id] = None
        if len(_seen_ids) > _SEEN_IDS_MAX:
            _seen_ids.popitem(last=False)
        return False


def on_trigger_event(
    event: TriggerEvent,
    fact_store: "FactStore",
    scheduler: "ProactiveScheduler",
) -> None:
    """Route a TriggerEvent into a scheduled proactive check-in.

    May block for ~hundreds of ms (the semantic memory query runs an
    embedding). Callers that hand off events from time-sensitive threads
    (e.g., the EventKit pump in ``CalendarMonitor``) should invoke this
    through a ``ThreadPoolExecutor`` rather than synchronously.
    """
    # ----- dedupe -----
    # Same event_id arriving twice (webhook retry, watchdog seeing a
    # write-then-rename, etc.) should fire one check-in, not two.
    if event.event_id and _seen_recently(event.event_id):
        return

    # ----- per-source filters -----

    if event.source == "calendar":
        meta = event.metadata or {}
        start_iso = meta.get("start")
        end_iso = meta.get("end")
        try:
            start_dt = datetime.fromisoformat(start_iso) if start_iso else None
            end_dt = datetime.fromisoformat(end_iso) if end_iso else None
        except ValueError:
            start_dt, end_dt = None, None
        if not start_dt or not end_dt:
            return
        starts_in = start_dt - datetime.now(start_dt.tzinfo or timezone.utc)
        if starts_in < timedelta(0):
            return  # already started or in the past
        if starts_in > CALENDAR_WAKE_HORIZON:
            return  # too far out to be actionable now
        if (end_dt - start_dt) < CALENDAR_MIN_DURATION:
            return  # short event, probably not worth interrupting for
        cal = meta.get("calendar")
        if cal and str(cal).lower() in {"birthdays", "holidays"}:
            return  # ignore noisy system calendars
        fire_at_base = start_dt
    else:
        fire_at_base = event.timestamp or datetime.now(timezone.utc)

    # ----- semantic fact recall -----

    query = f"{event.title}. {event.content}".strip()
    facts = fact_store.search(query, top_k=4, min_score=0.25) if query else []
    fact_lines = (
        "\n".join(f"- ({f.kind}) {f.text}" for f in facts) or "(none yet)"
    )

    # ----- decide fire time -----

    lead = timedelta(minutes=10) if event.source == "calendar" else timedelta(0)
    fire_at = fire_at_base - lead
    if fire_at.tzinfo is None:
        fire_at = fire_at.replace(tzinfo=timezone.utc)
    earliest = datetime.now(timezone.utc) + timedelta(minutes=1)
    if fire_at < earliest:
        fire_at = earliest

    # ----- build context payload -----

    if event.source == "calendar":
        meta = event.metadata or {}
        is_new = bool(meta.get("is_new", True))
        notes = meta.get("notes") or "(none)"
        verb = "added" if is_new else "updated"
        context = (
            f"{CALENDAR_WAKE_SENTINEL}\n"
            f"A calendar event you should react to was just {verb}.\n\n"
            f"EVENT: '{event.title}'\n"
            f"WHEN:  {meta.get('start')} to {meta.get('end')}\n"
            f"CAL:   {meta.get('calendar') or '(unknown)'}\n"
            f"NOTES: {notes}\n\n"
            f"What you know about the user that may be relevant:\n{fact_lines}\n\n"
            f"Decide whether to send a short, warm text NOW. If yes, draft the exact "
            f"message. If a future check-in (e.g., during the event) would be more useful, "
            f"also use schedule_proactive_check_in. If neither is warranted, reply SKIP."
        )
    else:
        context = (
            f"{TRIGGER_WAKE_SENTINEL}\n"
            f"An external signal arrived (source: {event.source}).\n\n"
            f"TITLE:   {event.title}\n"
            f"WHEN:    {event.timestamp.isoformat()}\n"
            f"CONTENT:\n{event.content}\n\n"
            f"What you know about the user that may be relevant:\n{fact_lines}\n\n"
            f"Decide whether to send a short, warm text NOW. If yes, draft the exact "
            f"message. If a future check-in would be more useful, also use "
            f"schedule_proactive_check_in. If neither is warranted, reply SKIP."
        )

    scheduler.schedule(
        conversation_id="summer-main",
        fire_at=fire_at,
        context=context,
    )
    print(
        f"[triggers] wake scheduled at {fire_at.astimezone().isoformat()} "
        f"for {event.source} event '{event.title}' (matched {len(facts)} facts)"
    )
