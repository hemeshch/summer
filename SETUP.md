# Stella Setup Guide

## Prerequisites

- macOS (for iMessage integration)
- Python 3.10+
- Anthropic API key

## Installation Steps

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Copy the example env file and add your API key:

```bash
cp .env.example .env
```

Edit `.env` and add your Anthropic API key:
```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx
```

Get your API key from: https://console.anthropic.com/

### 3. Set up iMessage integration

#### Create the Shortcut

1. Open **Shortcuts** app on macOS
2. Click **+** to create a new shortcut
3. Name it: **sendmessage**

#### Add Actions

Add these actions in order:

1. **Get File**
   - File path: `/Users/michel/Desktop/stella/shortcuts-ipc/in.txt`

2. **Get Text from Input**
   - (No configuration needed)

3. **Send Message**
   - Message: (output from previous action)
   - Recipient: Choose your contact or enter phone number

#### Test the Shortcut

Run the shortcut manually to verify it works:
1. Write a test message to the file:
   ```bash
   echo "Test message" > shortcuts-ipc/in.txt
   ```
2. Run the shortcut from Shortcuts app
3. Check if you received the message

### 4. Run Stella

```bash
python main.py
```

You should see:
```
=== Stella I/O System ===

Pipeline: WebSocket => Claude => iMessage

WebSocket URL: wss://channel-api.hemeshchadalavada.workers.dev/channels/stella
Model: claude-sonnet-4-5

Messages from the WebSocket will be processed by Claude,
and Claude's responses will be sent via iMessage.

[WebSocketTextInputProvider] Connecting...
[WebSocketTextInputProvider] Connected
```

## Troubleshooting

### "ANTHROPIC_API_KEY must be set"

Make sure:
- `.env` file exists in the `stella/` directory
- File contains `ANTHROPIC_API_KEY=your_key_here`
- API key is valid

### "shortcuts command not found"

Make sure you're on macOS. The `shortcuts` CLI tool is macOS-only.

### Shortcut not sending messages

Check:
- Shortcut is named exactly "sendmessage"
- File path in shortcut matches: `/Users/michel/Desktop/stella/shortcuts-ipc/in.txt`
- You have iMessage set up and working
- Recipient is configured correctly

### WebSocket not connecting

Check:
- Your internet connection
- The WebSocket URL is accessible
- No firewall blocking WebSocket connections

## Customization

### Change WebSocket Channel

Edit `main.py` and change the URL:
```python
ws_provider = WebSocketTextInputProvider(
    url="wss://your-websocket-url-here"
)
```

### Change Claude Model

Edit `main.py`:
```python
claude_block = ClaudeOutputBlock(
    model="claude-3-opus-20240229",  # or any other Claude model
    max_tokens=2048,
    system_prompt="Your custom prompt here"
)
```

### Change iMessage Recipient

Edit the "sendmessage" shortcut in Shortcuts app and change the recipient in the Send Message action.
