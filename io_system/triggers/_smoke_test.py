"""Manual smoke test for the trigger system.

Exercises the wiring without touching EventKit, IMAP, or the network:

    1. Confirm ``TriggerEvent`` instantiates with all fields.
    2. Run a synthetic ``MockTrigger`` end-to-end through ``start``/``stop``,
       asserting the callback receives the event.
    3. Feed a synthetic event into the same fact_store + scheduler bridge
       used by ``main_agentic.py`` and assert the bridge does not raise.
    4. Spot-check each real trigger's ``is_available()`` for sanity.

Run from the repo root:

    python -m io_system.triggers._smoke_test
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from io_system.triggers import (
    CalendarEventTrigger,
    EmailTrigger,
    EventTrigger,
    FileWatcherTrigger,
    TriggerEvent,
    WebhookTrigger,
)


class _MockTrigger(EventTrigger):
    """Test-only trigger that fires synthetic events on demand."""

    name = "mock"

    def __init__(self, on_event):
        super().__init__(on_event)
        self.started = False

    @classmethod
    def is_available(cls) -> bool:
        return True

    def start(self) -> None:
        self.started = True

    def stop(self, timeout: float = 5.0) -> None:
        self.started = False

    def fire(self, event: TriggerEvent) -> None:
        self._emit(event)


def _make_event(source: str = "calendar") -> TriggerEvent:
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    return TriggerEvent(
        source=source,
        title="deep work session",
        content=f"Calendar event: 'deep work session' {now} to {now + timedelta(hours=2)}. focus block",
        timestamp=now,
        metadata={
            "start": now.isoformat(),
            "end": (now + timedelta(hours=2)).isoformat(),
            "calendar": "Personal",
            "is_new": True,
            "notes": "focus block",
        },
        event_id="evt-smoke-1",
    )


def _check_dataclass() -> None:
    print("[1/4] TriggerEvent dataclass...")
    ev = _make_event()
    assert ev.source == "calendar"
    assert ev.title == "deep work session"
    assert ev.event_id == "evt-smoke-1"
    assert ev.metadata["is_new"] is True
    print("      OK")


def _check_mock_trigger() -> None:
    print("[2/4] MockTrigger callback...")
    captured: List[TriggerEvent] = []
    trig = _MockTrigger(on_event=captured.append)
    trig.start()
    assert trig.started
    trig.fire(_make_event(source="mock"))
    assert len(captured) == 1
    assert captured[0].source == "mock"
    trig.stop()
    assert not trig.started
    print("      OK")


class _StubEmbedder:
    """Deterministic, dependency-free embedder for tests.

    Returns an 8-dim vector derived from the text length so we don't need
    sentence-transformers (or any network) just to exercise the bridge.
    """

    dim = 8

    def embed(self, texts):
        out = []
        for t in texts:
            seed = float(len(t) or 1)
            out.append([seed * (i + 1) / 100.0 for i in range(self.dim)])
        return out


def _make_event_with_id(source: str, event_id: str) -> TriggerEvent:
    ev = _make_event(source)
    return TriggerEvent(
        source=ev.source,
        title=ev.title,
        content=ev.content,
        timestamp=ev.timestamp,
        metadata=ev.metadata,
        event_id=event_id,
    )


def _check_bridge() -> None:
    print("[3/4] on_trigger_event bridge...")
    # Local imports so a broken bridge surfaces a clear failure here rather
    # than at module import time.
    from io_system.context_engine import FactStore
    from io_system.proactive.scheduler import ProactiveScheduler
    from io_system.triggers import on_trigger_event as _on_trigger_event

    with tempfile.TemporaryDirectory() as tmp:
        fact_db = str(Path(tmp) / "facts.db")
        sched_db = str(Path(tmp) / "sched.db")
        store = FactStore(db_path=fact_db, embedder=_StubEmbedder())
        fires: List[dict] = []
        scheduler = ProactiveScheduler(
            db_path=sched_db,
            fire_callback=fires.append,
            poll_interval_seconds=5.0,
        )

        # Three distinct event_ids: bridge should schedule all three.
        _on_trigger_event(_make_event_with_id("calendar", "smoke-cal-1"), store, scheduler)
        _on_trigger_event(_make_event_with_id("webhook", "smoke-web-1"), store, scheduler)
        _on_trigger_event(_make_event_with_id("email", "smoke-mail-1"), store, scheduler)
        pending = scheduler.list_pending()
        print(f"      3 distinct event_ids → {len(pending)} pending (expected 3)")
        assert len(pending) == 3, f"expected 3 schedules, got {len(pending)}"

        # Same event_id repeated: dedupe should prevent additional schedules.
        _on_trigger_event(_make_event_with_id("webhook", "smoke-web-1"), store, scheduler)
        _on_trigger_event(_make_event_with_id("webhook", "smoke-web-1"), store, scheduler)
        pending_after_dup = scheduler.list_pending()
        print(f"      same event_id fired 2 more times → {len(pending_after_dup)} pending (expected still 3)")
        assert len(pending_after_dup) == 3, f"dedupe failed: got {len(pending_after_dup)}"
    print("      OK")


def _check_availability() -> None:
    print("[4/4] is_available() sanity...")
    for cls in [
        CalendarEventTrigger,
        EmailTrigger,
        WebhookTrigger,
        FileWatcherTrigger,
    ]:
        available = cls.is_available()
        assert isinstance(available, bool)
        print(f"      {cls.__name__}.is_available() = {available}")
    print("      OK")


def main() -> int:
    _check_dataclass()
    _check_mock_trigger()
    _check_bridge()
    _check_availability()
    print("\nAll trigger smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
