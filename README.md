# Stella - Rich Input/Output System

A modular Python framework for building input/output pipelines with streaming, event-driven architecture.

## What is Stella?

Stella connects:
- **WebSocket** (input) → **Claude AI** (processing) → **iMessage** (output)

Messages from a WebSocket channel are processed by Claude AI, and responses are sent via iMessage.

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API key

Add your Anthropic API key to `.env`:
```
ANTHROPIC_API_KEY=your_key_here
```

### 3. Set up iMessage integration

Create an Apple Shortcut named "sendmessage":
1. Open Shortcuts app on macOS
2. Create new shortcut
3. Add action: **Get File** → `/Users/michel/Desktop/stella/shortcuts-ipc/in.txt`
4. Add action: **Get Text from Input**
5. Add action: **Send Message** → Configure your recipient

See `shortcuts-ipc/README.md` for details.

### 4. Run Stella

```bash
python main.py
```

Messages sent to the WebSocket channel will be processed by Claude and forwarded to iMessage!

## Architecture

### Core Concepts

**Input Providers** - Stream inputs into the system
- `StdinInputProvider` - Read from stdin
- `WebSocketTextInputProvider` - Subscribe to WebSocket channels

**Inputs** - Messages flowing into the system
- `TextMessageInput` - Text messages

**Output Blocks** - Process inputs and produce outputs
- `IdentityOutputBlock` - Pass through (identity function)
- `ClaudeOutputBlock` - Process with Claude AI

**Outputs** - Messages produced by the system
- `TextMessageOutput` - Text messages
- `iMessageOutput` - iMessage messages

**Output Handlers** - Deliver outputs to destinations
- `create_imessage_handler()` - Send via iMessage/Shortcuts
- Functions that can be attached to any output block
- Separate delivery mechanism from processing logic

### Pipeline Flow

```
WebSocket Channel
      ↓
TextMessageInput
      ↓
ClaudeOutputBlock (processes with AI)
      ↓
TextMessageOutput
      ↓
iMessage Handler (sends via Shortcuts)
      ↓
iMessage App
```

## Configuration

### WebSocket URL

Default: `wss://channel-api.hemeshchadalavada.workers.dev/channels/stella`

Edit in `main.py` to change.

### Claude Settings

Edit in `main.py`:
- `model`: Default is `claude-sonnet-4-5`
- `max_tokens`: Default is 1024
- `system_prompt`: Customize Claude's behavior

### iMessage Settings

Edit the shortcut or change in handler:
- Recipient
- Message format
- IPC file path

## Extending Stella

### Add a Custom Output Block

```python
from io_system.base import OutputBlock
from io_system.inputs import TextMessageInput
from io_system.outputs import TextMessageOutput

class MyBlock(OutputBlock):
    def process_input(self, input_obj):
        if isinstance(input_obj, TextMessageInput):
            # Your processing logic
            result = input_obj.text.upper()

            # Emit output
            self.emit_output(TextMessageOutput(result))
```

### Add a Custom Output Handler

```python
def my_handler(output_obj):
    # Your delivery logic
    print(f"Sending: {output_obj.text}")
    # ... send to your destination

# Use with any block
block = IdentityOutputBlock(output_handler=my_handler)
```

### Add a Custom Input Provider

```python
from io_system.base import InputProvider
from io_system.inputs import TextMessageInput

class MyProvider(InputProvider):
    def start(self):
        # Your input logic
        while True:
            data = self.get_data()
            input_obj = TextMessageInput(data)
            self.notify_output_blocks(input_obj)
```

## File Structure

```
stella/
├── io_system/              # Main package
│   ├── base.py            # Base abstract classes
│   ├── inputs/            # Input types
│   ├── outputs/           # Output types
│   ├── providers/         # Input providers (stdin, websocket)
│   ├── blocks/            # Output blocks (identity, claude)
│   └── handlers/          # Output handlers (imessage)
├── shortcuts-ipc/         # IPC for macOS Shortcuts
├── main.py                # Main entry point
├── .env                   # API keys (not in git)
├── .env.example           # Example env file
├── requirements.txt       # Python dependencies
└── README.md              # This file
```

## Dependencies

- `anthropic` - Claude AI API
- `python-dotenv` - Environment variables
- `websocket-client` - WebSocket support

## License

MIT
