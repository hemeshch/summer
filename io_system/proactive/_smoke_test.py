"""Manual smoke test for the proactive scheduler.

Exercises the full wiring without hitting Anthropic or the Shortcuts handler:
runs a real ProactiveScheduler with a callback that captures what would fire,
schedules a row 1 second in the future, and asserts the callback ran.

Run from the repo root:
    python -m io_system.proactive._smoke_test
"""

import tempfile
import time
from datetime import datetime, timedelta, timezone

from io_system.proactive.scheduler import ProactiveScheduler


def main() -> None:
    captured = []

    def on_fire(row):
        print(f"  [fired] #{row['id']} conv={row['conversation_id']} context={row['context']!r}")
        captured.append(row)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    scheduler = ProactiveScheduler(
        db_path=db_path,
        fire_callback=on_fire,
        poll_interval_seconds=0.25,
    )
    scheduler.start()

    print(f"DB: {db_path}")
    print("Scheduling 3 check-ins (1 already-due, 1 in 1s, 1 in 60s)...")
    scheduler.schedule(
        "conv-smoke",
        datetime.now(timezone.utc) - timedelta(seconds=5),
        "should fire immediately",
    )
    scheduler.schedule(
        "conv-smoke",
        datetime.now(timezone.utc) + timedelta(seconds=1),
        "should fire after ~1s",
    )
    late_id = scheduler.schedule(
        "conv-smoke",
        datetime.now(timezone.utc) + timedelta(seconds=60),
        "should NOT fire during this test",
    )

    print(f"Pending before wait: {len(scheduler.list_pending())}")
    time.sleep(2.0)
    scheduler.stop()

    print(f"\nFired: {len(captured)} (expected 2)")
    print(f"Still pending: {len(scheduler.list_pending())} (expected 1)")
    assert len(captured) == 2, captured
    assert len(scheduler.list_pending()) == 1

    cancelled = scheduler.cancel(late_id)
    print(f"Cancelled #{late_id}: {cancelled}")
    assert cancelled
    assert len(scheduler.list_pending()) == 0
    print("\nOK")


if __name__ == "__main__":
    main()
