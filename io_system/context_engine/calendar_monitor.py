"""CalendarMonitor — event-driven wake-ups from Apple Calendar via EventKit.

Subscribes to EKEventStoreChangedNotification through PyObjC and fires a
callback whenever a calendar event is added or modified within our watch
window (default: next 48 hours). The agent uses this to wake itself in
response to a user adding e.g. "deep work 10pm–3am" to their calendar.

Threading model:
    EventKit posts NSNotifications on the thread that the EKEventStore was
    created on, AND the run loop must be pumped on that same thread. So we:
        1. Spawn a background thread.
        2. Inside the thread, create the EKEventStore, request access,
           register the observer, and pump NSRunLoop in 0.5s slices until
           stop() flips the event.
    The user-provided callback is invoked from this thread — keep it cheap
    or hand work off to a queue.

Graceful degradation:
    If PyObjC/EventKit is not importable (e.g., running on Linux, or PyObjC
    not installed), CalendarMonitor.is_available() returns False and start()
    is a no-op. This way main_agentic.py can wire the monitor unconditionally
    without breaking non-macOS environments.

Permissions:
    On first run, macOS will prompt the user for Calendar access. If denied,
    we log it and the monitor stays idle.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ----- public dataclass -----

@dataclass
class CalendarEventChange:
    """A single new-or-modified event we observed."""

    event_id: str
    title: str
    start: Optional[datetime]
    end: Optional[datetime]
    calendar: Optional[str]
    notes: str
    last_modified: Optional[datetime]
    is_new: bool  # True if id wasn't in the previous snapshot

    def starts_in(self) -> Optional[timedelta]:
        if self.start is None:
            return None
        return self.start - datetime.now(self.start.tzinfo or timezone.utc)


# ----- availability check -----

def _try_import_eventkit():
    """Return (EventKit, Foundation, objc) modules or None on failure."""
    try:
        import objc  # noqa: F401
        from Foundation import (  # noqa: F401
            NSDate,
            NSDefaultRunLoopMode,
            NSNotificationCenter,
            NSObject,
            NSRunLoop,
        )
        import EventKit  # noqa: F401
        return True
    except ImportError as e:
        logger.info("CalendarMonitor: EventKit/PyObjC not available (%s)", e)
        return False


_EVENTKIT_AVAILABLE = _try_import_eventkit()


# ----- helper: convert NSDate ↔ Python datetime -----

def _nsdate_to_dt(ns_date) -> Optional[datetime]:
    if ns_date is None:
        return None
    try:
        ts = float(ns_date.timeIntervalSince1970())
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return None


# ----- the monitor -----

EventChangeHandler = Callable[[CalendarEventChange], None]


class CalendarMonitor:
    """Event-driven calendar watcher.

    Usage:
        monitor = CalendarMonitor(on_event_changed=lambda ev: print(ev))
        if monitor.is_available():
            monitor.start()
        ...
        monitor.stop()
    """

    def __init__(
        self,
        on_event_changed: EventChangeHandler,
        watch_window_days: int = 2,
        emit_initial_snapshot: bool = False,
    ):
        self.on_event_changed = on_event_changed
        self.watch_window_days = watch_window_days
        self.emit_initial_snapshot = emit_initial_snapshot

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # event_id -> last_modified iso string. Updated only from the monitor thread.
        self._snapshot: Dict[str, str] = {}
        self._store = None
        self._observer = None
        self._started_at: Optional[datetime] = None

    @staticmethod
    def is_available() -> bool:
        return _EVENTKIT_AVAILABLE

    # ----- lifecycle -----

    def start(self) -> None:
        if not self.is_available():
            logger.info("CalendarMonitor.start(): EventKit unavailable; no-op")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._started_at = datetime.now(timezone.utc)
        self._thread = threading.Thread(
            target=self._run, name="CalendarMonitor", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ----- monitor thread -----

    def _run(self) -> None:
        # Import lazily so this module is safely importable on non-macOS.
        import objc
        from Foundation import (
            NSDate,
            NSDefaultRunLoopMode,
            NSNotificationCenter,
            NSObject,
            NSRunLoop,
        )
        import EventKit

        EKEventStore = EventKit.EKEventStore
        EKEntityTypeEvent = EventKit.EKEntityTypeEvent
        EKEventStoreChangedNotification = EventKit.EKEventStoreChangedNotification

        # The observer needs to be an NSObject subclass with an ObjC selector.
        # Defining the class inside _run keeps the dependency on PyObjC lazy.
        class _StoreObserver(NSObject):
            def initWithHandler_(self, handler):
                self = objc.super(_StoreObserver, self).init()
                if self is None:
                    return None
                self._handler = handler
                return self

            def storeChanged_(self, notification):
                try:
                    self._handler()
                except Exception:
                    logger.exception("CalendarMonitor: handler raised")

        store = EKEventStore.alloc().init()
        self._store = store

        # ----- request access -----
        access_granted = self._request_access(store, EKEntityTypeEvent)
        if not access_granted:
            logger.warning(
                "CalendarMonitor: calendar access not granted; monitor idle"
            )
            return

        # ----- observe store changes -----
        observer = _StoreObserver.alloc().initWithHandler_(self._on_store_changed)
        self._observer = observer
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            observer, b"storeChanged:", EKEventStoreChangedNotification, store
        )
        logger.info("CalendarMonitor: subscribed to EKEventStoreChangedNotification")

        # ----- seed snapshot so we don't fire for every existing event -----
        initial = self._query_window(store, EKEntityTypeEvent)
        self._snapshot = {
            e["event_id"]: e["last_modified"] for e in initial if e["event_id"]
        }
        logger.info(
            "CalendarMonitor: seeded snapshot with %d events in next %d days",
            len(self._snapshot), self.watch_window_days,
        )
        if self.emit_initial_snapshot:
            for e in initial:
                self._emit(e, is_new=True)

        # ----- pump the run loop until stop() -----
        run_loop = NSRunLoop.currentRunLoop()
        while not self._stop_event.is_set():
            until = NSDate.dateWithTimeIntervalSinceNow_(0.5)
            run_loop.runMode_beforeDate_(NSDefaultRunLoopMode, until)

        try:
            NSNotificationCenter.defaultCenter().removeObserver_(observer)
        except Exception:
            pass
        logger.info("CalendarMonitor: stopped")

    # ----- store change handling -----

    def _on_store_changed(self) -> None:
        if self._store is None:
            return
        try:
            import EventKit
            current = self._query_window(self._store, EventKit.EKEntityTypeEvent)
        except Exception:
            logger.exception("CalendarMonitor: failed to re-query window")
            return
        diff = self._diff(current)
        if diff:
            logger.info("CalendarMonitor: %d new/modified events", len(diff))
            for change in diff:
                self._emit(change["raw"], is_new=change["is_new"])
        # Update snapshot AFTER firing so handlers see the change exactly once.
        self._snapshot = {
            e["event_id"]: e["last_modified"] for e in current if e["event_id"]
        }

    def _diff(self, current: List[dict]) -> List[dict]:
        out = []
        for e in current:
            eid = e["event_id"]
            if not eid:
                continue
            prev_mod = self._snapshot.get(eid)
            if prev_mod is None:
                out.append({"raw": e, "is_new": True})
            elif e["last_modified"] and e["last_modified"] > prev_mod:
                out.append({"raw": e, "is_new": False})
        return out

    # ----- query helpers -----

    def _query_window(self, store, EKEntityTypeEvent) -> List[dict]:
        from Foundation import NSDate

        start = NSDate.date()  # now
        end = NSDate.dateWithTimeIntervalSinceNow_(
            self.watch_window_days * 24 * 3600
        )
        calendars = store.calendarsForEntityType_(EKEntityTypeEvent)
        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            start, end, calendars
        )
        ek_events = store.eventsMatchingPredicate_(predicate) or []
        out = []
        for ev in ek_events:
            try:
                eid = str(ev.eventIdentifier() or "")
                title = str(ev.title() or "")
                cal = ev.calendar()
                cal_name = str(cal.title()) if cal is not None else None
                start_dt = _nsdate_to_dt(ev.startDate())
                end_dt = _nsdate_to_dt(ev.endDate())
                notes = str(ev.notes() or "")
                last_mod = _nsdate_to_dt(ev.lastModifiedDate()) or _nsdate_to_dt(
                    ev.creationDate()
                )
                last_mod_iso = last_mod.isoformat() if last_mod else ""
                out.append(
                    {
                        "event_id": eid,
                        "title": title,
                        "start": start_dt,
                        "end": end_dt,
                        "calendar": cal_name,
                        "notes": notes,
                        "last_modified": last_mod_iso,
                    }
                )
            except Exception:
                logger.exception("CalendarMonitor: failed to read an event")
        return out

    def _emit(self, raw: dict, is_new: bool) -> None:
        change = CalendarEventChange(
            event_id=raw["event_id"],
            title=raw["title"],
            start=raw["start"],
            end=raw["end"],
            calendar=raw["calendar"],
            notes=raw["notes"],
            last_modified=(
                datetime.fromisoformat(raw["last_modified"])
                if raw["last_modified"]
                else None
            ),
            is_new=is_new,
        )
        try:
            self.on_event_changed(change)
        except Exception:
            logger.exception("CalendarMonitor: on_event_changed raised")

    # ----- access request -----

    def _request_access(self, store, EKEntityTypeEvent) -> bool:
        """Synchronously request calendar access.

        EventKit's request API is asynchronous and callback-based. We use a
        threading.Event to make it look sync to our caller.
        """
        done = threading.Event()
        result = {"granted": False, "error": None}

        def completion(granted, error):
            result["granted"] = bool(granted)
            result["error"] = error
            done.set()

        # Newer API (macOS 14+ / Sonoma): requestFullAccessToEventsWithCompletion_
        if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
            store.requestFullAccessToEventsWithCompletion_(completion)
        else:
            store.requestAccessToEntityType_completion_(
                EKEntityTypeEvent, completion
            )

        # Pump the run loop while we wait for the callback. The system
        # permission prompt blocks on first-ever request; give it generous
        # time.
        from Foundation import NSDate, NSDefaultRunLoopMode, NSRunLoop
        run_loop = NSRunLoop.currentRunLoop()
        deadline = datetime.now() + timedelta(seconds=60)
        while not done.is_set() and datetime.now() < deadline:
            run_loop.runMode_beforeDate_(
                NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.25)
            )
        if not done.is_set():
            logger.warning("CalendarMonitor: access request timed out")
            return False
        if result["error"] is not None:
            logger.warning("CalendarMonitor: access request error: %s", result["error"])
        return result["granted"]


# ----- module-level CLI for testing the permission/notification path -----

def _cli() -> int:
    import argparse
    import time

    p = argparse.ArgumentParser(
        description="Watch the calendar via EventKit and print changes."
    )
    p.add_argument(
        "--days", type=int, default=2, help="Look-ahead window in days"
    )
    p.add_argument(
        "--emit-initial",
        action="store_true",
        help="Also print events present at startup (default: only new/modified after start)",
    )
    args = p.parse_args()

    if not CalendarMonitor.is_available():
        print("EventKit not available. Install PyObjC: pip install pyobjc-framework-EventKit")
        return 2

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    def on_change(ev: CalendarEventChange):
        flag = "NEW" if ev.is_new else "MOD"
        starts_in = ev.starts_in()
        in_str = f"(in {starts_in})" if starts_in else ""
        print(
            f"  [{flag}] {ev.title!r} on {ev.calendar} "
            f"{ev.start} → {ev.end} {in_str}"
        )
        if ev.notes:
            print(f"        notes: {ev.notes[:100]}")

    monitor = CalendarMonitor(
        on_event_changed=on_change,
        watch_window_days=args.days,
        emit_initial_snapshot=args.emit_initial,
    )
    print(f"Starting CalendarMonitor (window={args.days}d). Ctrl-C to stop.")
    monitor.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping...")
        monitor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
