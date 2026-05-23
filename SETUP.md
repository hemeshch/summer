# Setting up Summer

Summer is a proactive AI agent that lives in iMessage. The pieces talk to each other like this:

```
   ┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
   │  iMessage on     │ ◄─────► │  Cloudflare      │ ◄─────► │  Python agent    │
   │  your phone /    │   ws    │  Worker          │   ws    │  on your Mac     │
   │  Mac             │         │  (worker/)       │         │  (agent + io)    │
   │                  │         │                  │         │                  │
   │  Sends prompts   │         │  WebSocket relay │         │  Claude loop,    │
   │  via Shortcuts   │         │  + broadcast     │         │  scheduler,      │
   │  bridge          │         │  fan-out         │         │  context engine  │
   └──────────────────┘         └──────────────────┘         └──────────────────┘
                                                                      │
                                                            ┌─────────┴─────────┐
                                                            │  Local SQLite     │
                                                            │  • proactive.db   │
                                                            │  • context_facts  │
                                                            │  • EventKit       │
                                                            └───────────────────┘
```

You'll set things up in this order: **Cloudflare Worker → Python env → macOS Shortcuts → grant calendar access → run it → (optional) Docker for the agent sandbox**. Each step's outputs feed the next.

Plan on 30–60 minutes the first time through.

---

## Prerequisites

| Component  | You need                                                                                  |
|------------|-------------------------------------------------------------------------------------------|
| Worker     | A Cloudflare account, Node.js 18+, `wrangler` CLI                                         |
| Agent      | macOS 13+ (for EventKit + iMessage), Python 3.10+, an Anthropic API key                   |
| Sandbox    | Docker Desktop (only if you want the `container_zsh` tool — full Linux env per conversation) |
| iMessage   | iMessage already signed in on the Mac you're running on (System Settings → Apple ID → iMessage) |

Install the CLIs:

```bash
brew install python@3.12 node
npm install -g wrangler
```

Grab your Anthropic API key: <https://console.anthropic.com/account/keys>.

> The default embedder is `sentence-transformers` (local, ~80MB model downloaded on first use, no API key). If you'd rather use OpenAI embeddings, set `SUMMER_EMBEDDER=openai` and add `OPENAI_API_KEY` to `.env`.

---

## 1. Cloudflare Worker (WebSocket relay)

There's a single Worker in `worker/`. It's a per-channel WebSocket fan-out: clients connect to `wss://.../channels/<id>`, messages POSTed to `/channels/<id>/broadcast` get pushed to every subscriber.

### 1a. Log in and pick a name

```bash
cd worker
wrangler login
```

Pick a Worker name — it has to be globally unique across Cloudflare. The default in `worker/wrangler.toml` is `channel-api`. Change the `name = ` field if you want something else:

```toml
# worker/wrangler.toml
name = "your-summer-relay"
```

For the rest of these docs, replace `YOUR_WORKER` with whatever subdomain you chose.

### 1b. Deploy

```bash
wrangler deploy
```

`wrangler` will print the public URL — save it. Something like `https://your-summer-relay.workers.dev`.

The Worker is stateless (no secrets to set, no DB, no D1, no KV) — just a Durable Object that holds WebSocket sessions in memory per channel.

### 1c. Smoke test

```bash
curl -X POST "https://YOUR_WORKER.workers.dev/create_channel?id=summer"
```

You should get back a JSON envelope with `websocketUrl` and `broadcastUrl`. If you don't, the rest of Summer won't work — debug here before moving on. The test page at `worker/websocket-test.html` is useful: open it in a browser, edit the URL at the top, and you can hand-send broadcasts to a live socket.

---

## 2. Python environment

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> The first run will download the sentence-transformers `all-MiniLM-L6-v2` model (~80MB) the first time the context engine touches an embedder. After that it's cached under `~/.cache/huggingface/`.

> If you also want the **full agentic sandbox** with the data-science / document-processing stack (LibreOffice, opencv, pdfplumber, scrapy, etc.), there's a separate manifest at `agent/requirements.txt` (~135 packages, ~3GB installed). You only need this if you're going to run inside the Docker container — see step 5 — or want every tool the agent ships with active locally. For the iMessage-only flow you don't need it.

### 2a. Configure environment

```bash
cp .env.example .env
```

Fill in `.env` — at minimum these four:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...

# WebSocket relay you just deployed
SUMMER_WEBSOCKET_URL=wss://YOUR_WORKER.workers.dev/channels/summer
WEBSOCKET_SERVER_URL=wss://YOUR_WORKER.workers.dev
BROADCAST_API_URL=https://YOUR_WORKER.workers.dev/broadcast
```

Optional knobs are documented inline in `.env.example`. Common ones:

| Variable                       | When you'd change it                                                   |
|--------------------------------|------------------------------------------------------------------------|
| `SUMMER_SCHEDULER_POLL_SECONDS`| Drop to `2` while smoke-testing so you don't wait 30s for a check-in to fire |
| `SUMMER_CALENDAR_MONITOR`      | Set to `0` to disable EventKit (e.g., running on a non-personal Mac)   |
| `SUMMER_EMBEDDER`              | Set to `openai` to use OpenAI embeddings instead of the local model    |
| `SUMMER_EMAIL_FIXTURE`         | Path to a JSONL file of fake emails — for demos without Gmail OAuth     |

---

## 3. macOS Shortcuts (iMessage bridge)

The agent sends iMessages by writing the message text to a file, then invoking an Apple Shortcut named **`sendmessage`** that picks up the file and sends it. You have to create that shortcut once.

### 3a. Create the `sendmessage` shortcut

1. Open **Shortcuts.app** on macOS.
2. Click **+** to create a new shortcut, name it exactly: **sendmessage** (lowercase, no space).
3. Add these actions in order:

   | # | Action                  | Configure                                                                    |
   |---|-------------------------|------------------------------------------------------------------------------|
   | 1 | **Get File**            | File path: `/Users/YOU/path/to/summer/shortcuts-ipc/in.txt` (your repo path) |
   | 2 | **Get Text from Input** | (no config)                                                                  |
   | 3 | **Send Message**        | Message: *Text from previous action*; Recipient: your phone number / iMessage contact |

4. Test it. Create the file first, then run the shortcut from the Shortcuts app:
   ```bash
   mkdir -p shortcuts-ipc
   echo "test from Summer setup" > shortcuts-ipc/in.txt
   ```
   Click ▶ on the shortcut — you should receive "test from Summer setup" in iMessage.

If you want the IPC file somewhere else, set `SUMMER_IPC_FILE` in `.env` and use that path in step 3a's **Get File** action.

### 3b. (Optional) Shortcut helpers for calendar/email tools

The agent ships with a `ShortcutsToolProvider` that can invoke additional shortcuts named `get_calendar_events` and `send_email`. These aren't required — the main loop uses native EventKit for calendar, and there's no email feature shipping yet. If you want to enable them later, create those shortcuts and place wrapper scripts under `shortcut-tools/` (or set `SUMMER_SHORTCUTS_DIR` to wherever you keep them).

---

## 4. Grant calendar access (one-time)

`main_agentic.py` starts a background `CalendarMonitor` that uses EventKit to wake the agent when a new calendar event is added. The first time you launch, macOS will pop a permission prompt — click **Allow**.

You can pre-trigger the prompt without starting the whole agent:

```bash
python -m io_system.context_engine.calendar_monitor --days 2
```

Add an event to Apple Calendar in another window — you should see it logged in the terminal. Ctrl-C when satisfied.

If you'd rather skip calendar wake-ups (e.g., on a work machine you don't want EventKit reading), set `SUMMER_CALENDAR_MONITOR=0` in `.env`.

---

## 5. Docker container for the agent sandbox (optional)

This is **only required if you want the `container_zsh` tool** — a sandboxed Ubuntu environment per conversation with LibreOffice, Pandoc, Python data-science libs, and friends. Without it, every other tool still works (file_system, recall_relevant_facts, add_fact_to_memory, schedule_proactive_check_in, place_doordash_order). Only `container_zsh` would error if invoked.

```bash
cd agent/summer/tools/linux_desktop_environment
./scripts/build-agent.sh
```

The build takes 10–20 minutes the first time and produces a `claude-agent:latest` image (~5GB).

If you don't want Docker at all, no action needed — `main_agentic.py` only registers `file_system` and `bash` as the base tools list, and `bash` does not require the container.

---

## 6. Run it

Two entry points:

```bash
# A. Full proactive agent — the actual product.
#    Wires the scheduler, context engine, EventKit monitor, semantic memory,
#    and all the proactive/recall/memory_write/doordash tools.
python main_agentic.py

# B. Bare relay. Just WebSocket → Claude → iMessage, no agentic loop.
#    Useful for sanity-checking your worker + iMessage setup before
#    bringing the agent up.
python main.py
```

On first run of `main_agentic.py` you'll see (abridged):

```
=== Summer Agentic I/O System ===
WebSocket URL:   wss://YOUR_WORKER.workers.dev/channels/summer
Scheduler DB:    /Users/you/.../summer/proactive.db
Fact DB:         /Users/you/.../summer/context_facts.db
Poll interval:   30.0s

[FactStore] loaded with 0 facts
[AgenticClaudeOutputBlock] Registered tool: schedule_proactive_check_in
[AgenticClaudeOutputBlock] Registered tool: recall_relevant_facts
[AgenticClaudeOutputBlock] Registered tool: add_fact_to_memory
[AgenticClaudeOutputBlock] Registered tool: place_doordash_order (stub)
[ContextEngine] next ingest scheduled for 2026-05-25T03:00:00-05:00
CalendarMonitor started (event-driven wake-ups via EventKit).
Scheduler started.
Pipeline started! Listening for messages...
```

### 6a. Seed the semantic memory for a demo

Before the agent has had any real conversations, the fact store is empty. To run a demo flow where the agent "remembers" things, seed it with curated facts:

```bash
python -m io_system.context_engine seed
python -m io_system.context_engine recall "what does the user do at 2am"
python -m io_system.context_engine facts
```

### 6b. Send a test message

With `main_agentic.py` running:

1. POST to your relay (or use `worker/websocket-test.html`):
   ```bash
   curl -X POST "https://YOUR_WORKER.workers.dev/channels/summer/broadcast" \
        -H "Content-Type: application/json" \
        -d '{"type":"new_prompt","recipient":"agent","payload":{"prompt":"hey just got to the library, got a midterm tomorrow"}}'
   ```
2. The terminal should show the agent receiving the prompt, optionally calling `recall_relevant_facts` and `schedule_proactive_check_in`, then sending a reply via iMessage.
3. Your phone buzzes.

If anything in that chain is silent, the troubleshooting section below tells you where to start.

---

## Verifying end-to-end

A 30-second sanity sweep after every fresh setup:

```bash
# 1. Worker is live
curl -sS "https://YOUR_WORKER.workers.dev/create_channel?id=summer" | jq

# 2. Python imports clean
python -c "import main_agentic; print('OK')"

# 3. Context engine round-trip (seeds + recalls)
python -m io_system.context_engine seed
python -m io_system.context_engine recall "late-night studying"

# 4. Scheduler sqlite + thread loop
python -m io_system.proactive._smoke_test

# 5. EventKit + permission
python -m io_system.context_engine.calendar_monitor --days 1
```

Each of these is independent — if one fails, the others can still pass and tell you which subsystem to focus on.

---

## Troubleshooting

| Symptom                                                       | Likely cause                                                              |
|---------------------------------------------------------------|----------------------------------------------------------------------------|
| `main_agentic.py` exits with "ANTHROPIC_API_KEY must be set"   | `.env` missing or key not set. `cp .env.example .env` and add the key.    |
| `ModuleNotFoundError: No module named 'summer'`                | The `agent/` directory isn't on `sys.path` because nothing imported `io_system.blocks.agentic_claude` first. Always start with `import main_agentic` or run `main_agentic.py` directly. |
| `shortcuts command not found`                                  | You're not on macOS, or `shortcuts` CLI is missing. The Shortcuts app must be installed (it's stock on macOS 13+). |
| Shortcut runs but no iMessage delivered                        | The "Send Message" action recipient is wrong, or iMessage isn't signed in. Try sending a regular iMessage from Messages.app first. |
| `[iMessageHandler] shortcuts command not found`                | Same as above; safe to ignore if you're testing without iMessage. Set `SUMMER_IPC_FILE` to `/dev/null` if you want to silence it entirely. |
| `Shortcuts tools directory not found at .../shortcut-tools`    | Only matters if you enabled `ShortcutsToolProvider`. Either create `shortcut-tools/` or set `SUMMER_SHORTCUTS_DIR`, or just don't enable that tool. |
| WebSocket says "Disconnected"                                  | `SUMMER_WEBSOCKET_URL` doesn't match what `wrangler deploy` printed. Hit the URL in a browser to confirm it's live. |
| CalendarMonitor logs "calendar access not granted"             | macOS denied the permission. Re-enable in System Settings → Privacy & Security → Calendar. Toggle on for your terminal / Python binary. |
| First `recall` is slow (~5–10s)                                | sentence-transformers is downloading the model on first use. Subsequent runs are fast. |
| `pip install` fails on `pyobjc-framework-EventKit`             | Only happens on non-macOS. `requirements.txt` already guards it with `sys_platform == "darwin"`, but if your pip resolver ignored that, drop it from the file. |
| `container_zsh` tool errors "Cannot connect to Docker daemon"  | Docker Desktop isn't running, or the `claude-agent:latest` image hasn't been built. See step 5. |
| Scheduler fires but no message arrives                         | Check the agent terminal — Claude may have decided to `SKIP`. That's a feature; tighten the system prompt in `main_agentic.py:SYSTEM_PROMPT` if it's skipping too eagerly. |

---

## Configuration reference

### Environment variables

| Variable                          | Required | Default                                            | Purpose                                                            |
|-----------------------------------|----------|----------------------------------------------------|--------------------------------------------------------------------|
| `ANTHROPIC_API_KEY`               | yes      | —                                                  | Claude API access                                                  |
| `SUMMER_WEBSOCKET_URL`            | yes      | `wss://your-worker.workers.dev/channels/summer`    | Channel the agent subscribes to                                    |
| `WEBSOCKET_SERVER_URL`            | yes      | `wss://your-worker.workers.dev`                    | Base WebSocket host                                                |
| `BROADCAST_API_URL`               | yes      | `https://your-worker.workers.dev/broadcast`        | HTTP broadcast endpoint                                            |
| `FILE_UPLOAD_API_URL`             | no       | `https://your-file-upload-api.workers.dev/upload`  | Optional file upload Worker (not deployed by default)              |
| `SUMMER_IPC_FILE`                 | no       | `<repo>/shortcuts-ipc/in.txt`                      | Path the `sendmessage` Shortcut reads from                         |
| `SUMMER_SHORTCUTS_DIR`            | no       | `<repo>/shortcut-tools`                            | Helper-scripts dir for the optional calendar/email shortcuts        |
| `SUMMER_SCHEDULER_DB`             | no       | `<repo>/proactive.db`                              | SQLite file for the proactive scheduler                            |
| `SUMMER_SCHEDULER_POLL_SECONDS`   | no       | `30`                                               | How often the scheduler polls for due check-ins                    |
| `SUMMER_FACT_DB`                  | no       | `<repo>/context_facts.db`                          | SQLite file for the semantic fact store                            |
| `SUMMER_EMBEDDER`                 | no       | `sentence-transformers`                            | `sentence-transformers` (local) or `openai` (needs `OPENAI_API_KEY`)|
| `OPENAI_API_KEY`                  | only if `SUMMER_EMBEDDER=openai` | — | OpenAI embeddings              |
| `SUMMER_EMAIL_FIXTURE`            | no       | —                                                  | JSONL file of fake emails for demos (no Gmail OAuth yet)           |
| `SUMMER_CALENDAR_MONITOR`         | no       | `1`                                                | Set `0` to disable EventKit calendar wake-ups                      |
| `SUMMER_SHOW_OVERLAY`             | no       | `true`                                             | Show the fullscreen "agent thinking" overlay during tool calls     |

### Worker URLs

| Endpoint                                  | Method | Purpose                                       |
|-------------------------------------------|--------|-----------------------------------------------|
| `/create_channel?id=<id>`                 | POST   | Create or join a channel; returns ws + broadcast URLs |
| `/channels/<id>`                          | GET (Upgrade) | WebSocket subscribe                    |
| `/channels/<id>/broadcast`                | POST   | Push a JSON message to every subscriber       |

### CLI entry points

| Command                                                          | What it does                                                         |
|------------------------------------------------------------------|----------------------------------------------------------------------|
| `python main_agentic.py`                                         | Full proactive agent (the actual product)                            |
| `python main.py`                                                 | Bare WebSocket → Claude → iMessage relay                             |
| `python -m io_system.context_engine seed`                        | Pre-populate the semantic memory with curated demo facts             |
| `python -m io_system.context_engine ingest --conversation-log <path>` | Run the nightly ingestion pipeline on demand                    |
| `python -m io_system.context_engine recall "<query>"`            | Semantic search the fact store                                       |
| `python -m io_system.context_engine facts`                       | List everything in the fact store                                    |
| `python -m io_system.context_engine.calendar_monitor`            | Run the EventKit monitor standalone (good for triggering the permission prompt) |
| `python -m io_system.proactive._smoke_test`                      | Verify the scheduler sqlite loop end-to-end                          |

### Tools the agent has access to

| Tool                            | What it does                                                              | When the agent uses it                                       |
|---------------------------------|---------------------------------------------------------------------------|---------------------------------------------------------------|
| `recall_relevant_facts`         | Semantic search over the user's fact store                                | Any time context might help                                   |
| `add_fact_to_memory`            | Write a fact directly into the semantic store (dedupes + reinforces)      | When the user confirms a habit or completes an action         |
| `schedule_proactive_check_in`   | Wake the agent at a future time with saved context                        | When the conversation has a natural follow-up moment          |
| `place_doordash_order` *(stub)* | Pretends to place an order; logs intent + writes a fact to memory         | After explicit user confirmation                              |
| `file_system`                   | Read/write/list files                                                     | For task execution                                            |
| `bash`                          | Shell commands on the host                                                | For task execution                                            |
| `container_zsh` *(optional)*    | Shell commands in a sandboxed Ubuntu container                            | Only if Docker is installed and the image built (step 5)      |
