# Summer

**A proactive AI agent that lives in iMessage and texts you before you even ask.**

**November 2025.**

<p align="center">
  <a href="https://www.youtube.com/watch?v=g5qqRE_QjgU" target="_blank" rel="noopener noreferrer">
    <img src="https://img.youtube.com/vi/g5qqRE_QjgU/maxresdefault.jpg" alt="Watch the Summer demo" width="700"/>
  </a>
</p>

<p align="center">
  <a href="https://www.youtube.com/watch?v=g5qqRE_QjgU" target="_blank" rel="noopener noreferrer"><b>Watch the demo</b></a>
  &nbsp;·&nbsp;
  <a href="https://hemesh.tech/builds/summer-ai" target="_blank" rel="noopener noreferrer">Build log</a>
  &nbsp;·&nbsp;
  <a href="./SETUP.md">Setup guide</a>
</p>

---

## the idea

AI chat today is reactive. Summer texts you first, in iMessage.

> "damn it's 2am 💀"
> "you're probably grinding for that midterm in the library"
> "wanna get our usual matcha latte from agora .."

Character.ai showed people want AI that feels alive. ChatGPT showed they want AI that's useful. Summer combines both, with a real **context engine** underneath: a background loop that ingests your day, extracts patterns, schedules future instances of the agent, and wakes up at the right moment with the right tools.

---

## the closed loop

Summer is an agent that schedules other agents to run. Calendar is the canonical trigger below. Any `EventTrigger` (email arrival, webhook push, file drop) fires the same flow.

```
   User adds "deep work 10pm-3am" to Apple Calendar
         │
         ▼
   EKEventStoreChangedNotification (EventKit, native macOS)
         │
         ▼
   CalendarEventTrigger diffs snapshot → new event
         │
         ▼
   Bridge queries semantic memory: search("deep work / late night")
         │  →  matcha pattern + Fondren pattern + COMP 326 fact surface
         ▼
   ProactiveScheduler.schedule(fire_at=9:50pm, context=event + retrieved facts)
         │
         ▼  ⏳ [hours pass; sqlite persists across restarts]
         ▼
   Scheduler thread claims the due row atomically
         │
         ▼
   Claude wakes up with the saved context as a synthetic prompt,
   can call recall_relevant_facts to dig deeper
         │
         ▼
   "damn it's 2am 💀 want your usual?"
         │
         ▼
   User: "yes"
         │
         ▼
   Claude calls place_doordash_order(item, restaurant)
         │
         ▼
   Tool auto-writes a fact back into semantic memory:
   "user confirmed matcha at 2am during library sessions"
         │
         ▼
   Next time → the memory is reinforced. Confidence climbs.
```

Every arrow in that diagram is a real subsystem. The next sections walk through each.

---

## the stack

| Layer                   | What it is                                                                                                                                                                                          |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Agent loop**          | Claude (Sonnet 4.6 / Opus 4.7) with tool-use, custom retry + backup-model fallback                                                                                                                  |
| **Tools**               | 130+ callable capabilities (see [tool surface](#tool-surface) below): first-party Python tools for memory, scheduling, calendar, email, plus a sandboxed Ubuntu container exposing the entire shell |
| **Proactive scheduler** | sqlite + WAL, atomic `BEGIN IMMEDIATE` claim, background polling thread, sentinel-based dispatch                                                                                                    |
| **Context engine**      | Pluggable sources → Claude-driven fact extractor → semantic store                                                                                                                                   |
| **Semantic memory**     | sqlite + `sentence-transformers/all-MiniLM-L6-v2` embeddings (pluggable to OpenAI), cosine search, similarity dedupe, confidence merging                                                            |
| **Wake-up triggers**    | Extensible `EventTrigger` interface. Built-in: calendar (EventKit native), email (IMAP + fixture), webhook (HTTP push), file watcher (filesystem events)                                            |
| **Surface**             | iMessage via macOS Shortcuts; WebSocket relay on a Cloudflare Worker (Durable Object) for two-way fan-out                                                                                           |

The whole thing is Python on macOS plus a few hundred lines of JS on the edge.

---

## the context engine

This is the core innovation. Summer's memory is a real semantic index, built by an unsupervised nightly loop and queried by the agent on demand.

**End-to-end:**

1. **Sources.** Pluggable `DataSource` implementations: `ConversationLogSource` (reads a JSONL the agent writes per turn), `AppleCalendarSource` (Shortcuts pull), `EmailSource` (fixture-backed; Gmail OAuth is next).
2. **Extractor.** `FactExtractor` sends the day's batch to Claude with a system prompt that explicitly asks for two kinds of output:
   - **Explicit facts** (e.g., "user has a COMP 326 midterm on 2026-05-23")
   - **Inferred patterns** (e.g., recurring 2am Agora receipts → "user orders matcha latte from Agora Coffee around 2am during late-night work sessions")
3. **Store.** `FactStore` uses sqlite for durability, stores embedding vectors as JSON, and does in-memory cosine search. Brute force is fine to ~100k facts; FAISS swaps in behind the same interface when we scale past that.

Facts go through **similarity-based dedupe on insert**. If an incoming fact has cosine similarity ≥ 0.92 with an existing row, we merge instead of inserting. Confidence merges via `1 − (1 − a) · (1 − b)` so corroboration is monotone and bounded. Source refs accumulate. After thirty weeks of corroboration, "user wants matcha at 2am" is one row with confidence approaching 1.0 and thirty source refs proving it.

**The orchestrator** (`ContextEngine.run_daily_ingest()`) is self-scheduling. After every ingest, it inserts a new row into the proactive scheduler for the next 3am, tagged with a sentinel that the scheduler's dispatch routes back to the engine instead of to Claude.

```python
INGEST_SENTINEL = "__SUMMER_NIGHTLY_INGEST__"

def on_fired(row):
    if row["context"].startswith(INGEST_SENTINEL):
        context_engine.run_daily_ingest()
        _ensure_ingest_scheduled(scheduler)
    else:
        block.process_proactive_check_in(row["context"])
```

One scheduler, two purposes, no extra plumbing.

---

## the scheduler

`ProactiveScheduler` is the heartbeat. Anything that needs to happen later goes through it: a check-in the agent decided to schedule, a nightly ingest, a calendar-triggered wake-up.

Implementation details that matter:

- **Sqlite with WAL** so the background polling thread and tool calls from the agent loop don't deadlock on writes.
- **Atomic claim via `BEGIN IMMEDIATE` + UPDATE-by-id** so two pollers can't double-fire the same row. The transaction selects all due rows, marks them `fired`, commits, then the fire callback runs outside the transaction.
- **Sentinel-based dispatch** in the fire callback. Rows whose `context` starts with a namespaced sentinel (`__SUMMER_NIGHTLY_INGEST__`, `__SUMMER_CALENDAR_WAKE__`) are routed to system handlers; everything else goes to the agent.
- **Survives restarts.** The sqlite file lives at `proactive.db`. Kill the process at 11pm; the 2am check-in still fires.

Exposed to the agent as a tool:

```python
schedule_proactive_check_in(delay_minutes: float, context: str)
```

The `context` is a free-form note Claude writes to its future self. When the row fires, that note becomes the synthetic prompt for the next Claude call.

---

## wake-up triggers

External signals fire the agent without a user prompt. Calendar is the canonical case. Email arrivals, HTTP webhooks, and files landing in a watched directory all flow through the same abstraction.

Every trigger implements one interface:

```python
class EventTrigger(ABC):
    name: str

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self, timeout: float = 5.0) -> None: ...

    def __init__(self, on_event: Callable[[TriggerEvent], None]): ...
```

Each trigger fires a `TriggerEvent` into one bridge function (`io_system/triggers/bridge.py:on_trigger_event`) that:

1. Dedupes by `event_id` via a thread-safe LRU set (4096 entries), so webhook retries and watchdog write-then-rename sequences don't double-fire.
2. Applies per-source filters (e.g., skip calendar events shorter than 20 min, ignore the Birthdays / Holidays calendars).
3. Queries the semantic fact store for context relevant to the event.
4. Schedules a proactive check-in whose payload bundles the event with the retrieved facts.

The bridge runs through a `ThreadPoolExecutor(max_workers=2)` so the embedding call (~hundreds of ms) doesn't stall the EventKit pump or watchdog observer thread.

Today's triggers:

| Trigger                | Mechanism                         | Notes                                                                                 |
| ---------------------- | --------------------------------- | ------------------------------------------------------------------------------------- |
| `CalendarEventTrigger` | EventKit via PyObjC               | Pushes via `EKEventStoreChangedNotification`; not polled. See deep-dive below.        |
| `EmailTrigger`         | IMAP polling + JSONL fixture      | First poll seeds `last_uid` to current max so the existing inbox does not replay.     |
| `WebhookTrigger`       | stdlib `http.server` on 127.0.0.1 | Optional shared-secret via `X-Summer-Token` (constant-time compare); 64 KiB body cap. |
| `FileWatcherTrigger`   | `watchdog` filesystem events      | Watches comma-separated paths from `SUMMER_FILE_WATCH_PATHS`.                         |

Each one's `is_available()` returns False if its dependency is missing (PyObjC on Linux, watchdog not installed, etc.) and `start()` becomes a no-op. The rest of the system runs.

### Calendar deep-dive: native EventKit subscription

EventKit on macOS pushes notifications via `EKEventStoreChangedNotification`. Summer subscribes to that signal directly through PyObjC. The threading model is the tricky bit:

> EventKit posts `NSNotifications` on the thread that created the `EKEventStore`, and that thread must be pumping an `NSRunLoop` for the notification to actually be delivered.

So:

1. Spawn a daemon thread.
2. Inside it, create the `EKEventStore`, request access (asynchronously; pump the run loop while waiting for the user to click "Allow"), register an observer.
3. Pump `NSRunLoop.currentRunLoop()` in 0.5s slices until `stop_event` flips.
4. On every notification, re-query the look-ahead window, diff against the stored snapshot (by `event_id` + `lastModifiedDate`), fire a Python callback per new/modified event.

```python
class _StoreObserver(NSObject):
    def initWithHandler_(self, handler):
        self = objc.super(_StoreObserver, self).init()
        self._handler = handler
        return self

    def storeChanged_(self, notification):
        self._handler()

NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
    observer, b"storeChanged:", EKEventStoreChangedNotification, store
)
```

### Adding a new trigger

Subclass `EventTrigger`, implement three methods, register the class in `main.py:trigger_classes`. That's it:

```python
class SlackTrigger(EventTrigger):
    name = "slack"

    @classmethod
    def is_available(cls) -> bool:
        try:
            import slack_sdk  # noqa: F401
            return bool(os.environ.get("SLACK_BOT_TOKEN"))
        except ImportError:
            return False

    def start(self) -> None:
        # Spin up the listener; call self._emit(TriggerEvent(...)) on each message.
        ...

    def stop(self, timeout: float = 5.0) -> None:
        ...
```

The bridge does the rest. Same dedupe, same semantic query, same proactive scheduling.

---

## tool surface

The agent has 130+ callable capabilities. They come from three places:

**First-party tools** (registered Python providers, ~13 currently enabled):

| Tool                                                     | What it does                                                        |
| -------------------------------------------------------- | ------------------------------------------------------------------- |
| `recall_relevant_facts`                                  | Semantic search over the user's fact store                          |
| `add_fact_to_memory`                                     | Direct write into the fact store with dedupe and confidence merging |
| `schedule_proactive_check_in`                            | Agent schedules a future wake-up of itself                          |
| `place_doordash_order`                                   | Stubbed order placement that also records the action as a fact      |
| `list_files` / `read_file` / `write_file` / file ops     | Filesystem access on the host                                       |
| `view_photo`                                             | Image analysis via Claude vision                                    |
| `container_zsh` / `container_status` / `container_reset` | Shell into the sandboxed Linux container (see below)                |
| `get_calendar_events`                                    | Apple Calendar read via Shortcuts                                   |
| `send_email`                                             | Apple Mail send via Shortcuts                                       |
| `analyze_own_codebase` / `discover_codebase_structure`   | Self-analysis via the Claude Code SDK                               |
| `submit_file_to_user`                                    | Upload a file produced inside the container to the user             |

**Sandboxed Linux environment** (exposed through `container_zsh`, runs an Ubuntu 24.04 container per conversation):

- ~50 apt packages: `pandoc`, `texlive-full` (500+ LaTeX binaries), `libreoffice`, `imagemagick`, `ghostscript`, `poppler-utils`, `qpdf`, `tesseract-ocr`, `ffmpeg`, `openjdk-21`, Node.js 18, build toolchain
- ~100 default Ubuntu utilities the agent can call directly: `grep`, `awk`, `sed`, `find`, `jq`, `curl`, `wget`, `ssh`, `rsync`, `git`, `tar`, `zip`, ...
- ~50 Python libraries: `numpy`, `pandas`, `scipy`, `scikit-learn`, `matplotlib`, `plotly`, `opencv-python`, `pdfplumber`, `python-pptx`, `markitdown`, `playwright`, `beautifulsoup4`, `lxml`, ...
- npm side: Playwright, `pptxgenjs`, `pdf-lib`, `marked`, `typescript`, `sharp`, ...

The container is built from `agent/summer/tools/linux_desktop_environment/docker/Dockerfile`. The agent can run any shell command, install ad-hoc packages, and surface results back through `submit_file_to_user`.

**Wake-up triggers** (the inputs that fire the agent without a user prompt):

| Trigger                | Mechanism                                                     |
| ---------------------- | ------------------------------------------------------------- |
| `CalendarEventTrigger` | EventKit native via PyObjC, `EKEventStoreChangedNotification` |
| `EmailTrigger`         | IMAP polling + JSONL fixture mode for demos                   |
| `WebhookTrigger`       | HTTP endpoint at `/trigger`, shared-secret auth               |
| `FileWatcherTrigger`   | `watchdog`-based filesystem events on configured paths        |

All four implement the same `EventTrigger` interface and route through one bridge function that queries the fact store and schedules a proactive check-in. Adding the next source (Slack, SMS, Spotify, Strava) is a single class.

---

## technical highlights

A handful of things worth pointing out in the code:

- **Self-scheduling agents.** The agent can call `schedule_proactive_check_in(delay_minutes, context)` mid-conversation. The scheduler persists the row, fires it on time, and re-invokes Claude with that saved context as a fresh prompt. Conversation history carries forward; Claude can opt out by responding `SKIP`.
- **Closed memory loop.** `add_fact_to_memory` writes directly into the semantic store (with dedupe + confidence merging) the moment the agent learns something. No waiting for the next nightly ingest. The next query finds the reinforced fact, whether it comes minutes, hours, or weeks later.
- **Extensible wake-up surface.** Four triggers ship today (calendar, email, webhook, file watcher), all behind the same `EventTrigger` ABC. The bridge handles event-id dedupe and dispatches expensive work through a worker pool so latency-sensitive trigger threads stay responsive. Adding the fifth source (Slack, SMS, Strava, Spotify) is one class.
- **Sentinel-based scheduler routing.** One scheduler handles four kinds of jobs (user-facing check-ins, nightly ingestion, calendar wake-ups, generic trigger wake-ups) with no extra plumbing, just a prefix on the `context` field.
- **Pluggable embedder.** Default is local sentence-transformers (no API key, ~80MB model). Set `SUMMER_EMBEDDER=openai` and add `OPENAI_API_KEY` to swap to `text-embedding-3-small` (~$0.02/M tokens). Same interface, same store, different backend.
- **Graceful degradation everywhere.** EventKit unavailable → `CalendarEventTrigger` is a no-op. watchdog not installed → `FileWatcherTrigger.is_available()` returns False. Docker not installed → `container_zsh` errors only if invoked. Shortcuts not configured → iMessage handler logs the message and moves on. No subsystem brings down the rest.

---

## try it

```bash
git clone <repo>
cd summer
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY + your worker URL

# seed the memory so the demo flow has something to recall
python -m io_system.context_engine seed
python -m io_system.context_engine recall "what does the user do at 2am"

# run the full agent
python main.py
```

Full setup (Cloudflare Worker deploy, iMessage Shortcut, calendar permission) is in **[SETUP.md](./SETUP.md)**.

---

## layout

```
summer/
├── main.py                     # full proactive agent, the actual product
├── examples/
│   └── basic_relay.py          # bare WebSocket → Claude → iMessage relay
├── io_system/
│   ├── proactive/
│   │   └── scheduler.py        # sqlite-backed, atomic claim, daemon thread
│   ├── triggers/
│   │   ├── base.py             # EventTrigger ABC + TriggerEvent dataclass
│   │   ├── bridge.py           # event → dedupe → fact recall → schedule
│   │   ├── calendar.py         # EventKit via PyObjC, NSRunLoop
│   │   ├── email.py            # IMAP polling + JSONL fixture
│   │   ├── webhook.py          # stdlib http.server, shared-secret auth
│   │   └── file_watcher.py     # watchdog filesystem events
│   ├── context_engine/
│   │   ├── embedder.py         # sentence-transformers (default) / OpenAI
│   │   ├── fact_store.py       # sqlite + cosine, dedupe + confidence merge
│   │   ├── extractor.py        # Claude → structured facts
│   │   ├── engine.py           # nightly orchestrator
│   │   ├── sources/            # conversation, calendar, email
│   │   └── cli.py              # python -m io_system.context_engine ...
│   ├── blocks/agentic_claude.py
│   ├── providers/              # WebSocket / stdin inputs
│   └── handlers/imessage.py    # Shortcuts-based iMessage send
├── agent/summer/
│   ├── claude_agent.py         # Claude loop, retry, backup-model fallback
│   ├── tool_system.py          # tool registry, validation, state
│   └── tools/
│       ├── recall_tool.py             # semantic search over the fact store
│       ├── memory_write_tool.py       # direct write into the fact store
│       ├── proactive_tool.py          # agent schedules its own wake-ups
│       ├── doordash_tool.py           # stub; auto-records the order as a fact
│       └── …                          # filesystem, container_zsh, view_photo, etc.
└── worker/
    └── worker.js               # Cloudflare Durable Object, WebSocket fan-out
```
