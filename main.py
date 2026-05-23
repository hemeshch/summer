#!/usr/bin/env python3
"""Summer Agentic — full pipeline.

WebSocket ⇒ Agentic Claude (with tools) ⇒ iMessage, plus:

  * ProactiveScheduler: agent can schedule future wake-ups of itself
  * Background ContextEngine: nightly ingestion of conversation/calendar/email
    signals into a semantic fact store
  * recall_relevant_facts tool: the agent searches that store by meaning

Setup required:
  - ANTHROPIC_API_KEY in .env
  - "sendmessage" shortcut in macOS Shortcuts (see SETUP.md)
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from io_system import WebSocketTextInputProvider, AgenticClaudeOutputBlock
from io_system.context_engine import (
    ContextEngine,
    FactExtractor,
    FactStore,
    build_default_embedder,
)
from io_system.context_engine.sources import (
    AppleCalendarSource,
    ConversationLogSource,
    EmailSource,
)
from io_system.handlers import create_imessage_handler
from io_system.proactive.scheduler import ProactiveScheduler
from io_system.triggers import (
    CalendarEventTrigger,
    EmailTrigger,
    EventTrigger,
    FileWatcherTrigger,
    TriggerEvent,
    WebhookTrigger,
    on_trigger_event as _on_trigger_event,
)


# Sentinel for the nightly context-engine ingest job. The agent never
# produces this organically.
INGEST_SENTINEL = "__SUMMER_NIGHTLY_INGEST__"


SYSTEM_PROMPT = """You are Summer — a proactive, friendly AI agent that lives in iMessage.

Your special tools beyond reading and writing files:

1. recall_relevant_facts — query your semantic memory of the user. The background
   context engine has been ingesting the user's conversations, calendar, and emails
   and storing facts/patterns/preferences. ALWAYS call recall first when the
   conversation surfaces a time-of-day, a place, a habit, or a recurring situation.
   Don't ask the user things you might already know.

2. add_fact_to_memory — write something you just learned back into memory. Call
   this the moment the user confirms a habit ('yes I want my usual matcha'),
   states a preference, or completes an action you should remember (an order
   placed, a meeting accepted). Reinforcing existing facts is good — the store
   merges duplicates and bumps confidence.

3. schedule_proactive_check_in — set a future moment to message the user, unprompted.
   Use it when the conversation has a natural follow-up moment (a midterm tomorrow
   morning, a flight at 6pm, "I'm grinding in the library tonight"). Pass
   `delay_minutes` for when, and `context` as a note to your future self.

4. place_doordash_order — place a DoorDash order. ONLY after the user explicitly
   confirms. After it succeeds, briefly tell the user (e.g., 'placed — ETA 15 min').
   The tool auto-updates memory; you don't need to call add_fact_to_memory for the
   order itself, but DO add a separate fact if the confirmation revealed a new
   pattern (e.g., 'user wants matcha at 2am during library sessions').

5. file system / bash — for general task execution.

CORE BEHAVIOR — PROACTIVITY:
You don't only respond. You anticipate. Use the memory + the scheduler together:
recall what you know, schedule a future moment if it adds value, write what you
learn back. One thoughtful check-in beats five noisy ones.

Keep replies short and warm — texting a friend, not writing an essay."""


def _next_3am_utc() -> datetime:
    """Return the next 3am in the local timezone, expressed as UTC."""
    now = datetime.now().astimezone()
    target = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target.astimezone(timezone.utc)


def _ensure_ingest_scheduled(scheduler: ProactiveScheduler) -> None:
    """Schedule the next nightly ingest if one isn't already pending."""
    pending = scheduler.list_pending()
    for row in pending:
        if row["context"].startswith(INGEST_SENTINEL):
            return
    fire_at = _next_3am_utc()
    scheduler.schedule(
        conversation_id="__system__",
        fire_at=fire_at,
        context=INGEST_SENTINEL,
    )
    print(f"[ContextEngine] next ingest scheduled for {fire_at.astimezone().isoformat()}")


def main():
    websocket_url = os.environ.get(
        "SUMMER_WEBSOCKET_URL",
        "wss://your-worker.workers.dev/channels/summer",
    )
    repo_root = Path(__file__).resolve().parent
    scheduler_db = os.environ.get(
        "SUMMER_SCHEDULER_DB", str(repo_root / "proactive.db")
    )
    fact_db = os.environ.get(
        "SUMMER_FACT_DB", str(repo_root / "context_facts.db")
    )
    poll_interval = float(os.environ.get("SUMMER_SCHEDULER_POLL_SECONDS", "30"))

    print("=== Summer Agentic I/O System ===")
    print(f"WebSocket URL:   {websocket_url}")
    print(f"Scheduler DB:    {scheduler_db}")
    print(f"Fact DB:         {fact_db}")
    print(f"Poll interval:   {poll_interval}s")
    print(f"Now:             {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # ----- core wiring -----

    ws_provider = WebSocketTextInputProvider(url=websocket_url)
    imessage_handler = create_imessage_handler()

    fact_store = FactStore(db_path=fact_db, embedder=build_default_embedder())
    print(f"[FactStore] loaded with {fact_store.count()} facts")

    def _placeholder(row):
        print(f"[main] scheduler fired before block was wired: {row}")

    scheduler = ProactiveScheduler(
        db_path=scheduler_db,
        fire_callback=_placeholder,
        poll_interval_seconds=poll_interval,
    )

    block = AgenticClaudeOutputBlock(
        output_handler=imessage_handler,
        system_prompt=SYSTEM_PROMPT,
        model="claude-sonnet-4-6",
        max_tokens=4096,
        enabled_tools=["file_system", "bash"],
        scheduler=scheduler,
        fact_store=fact_store,
    )

    # ----- background context engine -----

    context_engine = ContextEngine(
        sources=[
            ConversationLogSource(log_path=str(block.conversation_log_path)),
            EmailSource(),         # honors SUMMER_EMAIL_FIXTURE; no-op without it
            AppleCalendarSource(), # no-op if Shortcuts isn't configured
        ],
        extractor=FactExtractor(),
        store=fact_store,
    )

    # ----- dispatch fired check-ins -----

    def on_fired(row):
        context = row["context"]
        if context.startswith(INGEST_SENTINEL):
            print("[ContextEngine] nightly ingest firing")
            try:
                report = context_engine.run_daily_ingest()
                print(f"[ContextEngine] {report.summary()}")
            except Exception as e:
                print(f"[ContextEngine] ingest failed: {e}")
            finally:
                _ensure_ingest_scheduled(scheduler)
            return
        block.process_proactive_check_in(
            context=context, conversation_id=row.get("conversation_id")
        )

    scheduler.fire_callback = on_fired
    ws_provider.connect_output_block(block)

    _ensure_ingest_scheduled(scheduler)

    # ----- external triggers (calendar, email, webhook, file watcher) -----

    # The bridge does a semantic search (embedding takes ~hundreds of ms).
    # Running it on the trigger's own thread would stall calendar event
    # delivery (NSRunLoop pump) and any other latency-sensitive callback.
    # Dispatch through a small worker pool instead. One worker is plenty
    # since events are infrequent; we use two for headroom.
    trigger_executor = ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="trigger-bridge"
    )

    def _trigger_callback(ev: TriggerEvent) -> None:
        trigger_executor.submit(_on_trigger_event, ev, fact_store, scheduler)

    trigger_classes = [
        CalendarEventTrigger,
        EmailTrigger,
        WebhookTrigger,
        FileWatcherTrigger,
    ]
    # Honor the legacy SUMMER_CALENDAR_MONITOR flag so existing setups keep
    # behaving the same when they flip it to 0.
    if os.environ.get("SUMMER_CALENDAR_MONITOR", "1") == "0":
        os.environ.setdefault("SUMMER_TRIGGER_CALENDAR", "0")

    triggers: list[EventTrigger] = []
    for cls in trigger_classes:
        if not cls.is_available():
            print(f"[triggers] {cls.__name__} unavailable; skipping")
            continue
        env_var = f"SUMMER_TRIGGER_{cls.name.upper()}"
        if os.environ.get(env_var, "1") == "0":
            print(f"[triggers] {cls.__name__} disabled via {env_var}=0")
            continue
        try:
            t = cls(on_event=_trigger_callback)
            t.start()
        except Exception as e:
            print(f"[triggers] {cls.__name__} failed to start: {e}")
            continue
        triggers.append(t)
        print(f"[triggers] started {cls.__name__}")

    scheduler.start()
    print("Scheduler started.")
    print("Pipeline started! Listening for messages...\n")
    ws_provider.start()

    try:
        ws_provider.wait()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        for t in triggers:
            try:
                t.stop()
            except Exception:
                pass
        trigger_executor.shutdown(wait=False)
        scheduler.stop()
        ws_provider.stop()
        print("Goodbye!")


if __name__ == "__main__":
    main()
