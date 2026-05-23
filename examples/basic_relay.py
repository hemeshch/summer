#!/usr/bin/env python3
"""Bare WebSocket -> Claude -> iMessage relay.

Minimal example pipeline (no tools, no scheduler, no context engine):
  1. Receives messages from a WebSocket channel
  2. Processes them through Claude
  3. Sends Claude's responses via iMessage

For the full proactive agent, run ``main.py`` at the repo root instead.

Setup required:
  - Add ANTHROPIC_API_KEY to .env
  - Create "sendmessage" shortcut in macOS Shortcuts (see shortcuts-ipc/README.md)
"""

import os
import sys
from pathlib import Path

# Allow running from the repo root: `python examples/basic_relay.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from io_system import WebSocketTextInputProvider, ClaudeOutputBlock  # noqa: E402
from io_system.handlers import create_imessage_handler  # noqa: E402


def main():
    websocket_url = os.environ.get(
        "SUMMER_WEBSOCKET_URL",
        "wss://your-worker.workers.dev/channels/summer",
    )

    print("=== Summer I/O System ===")
    print("\nPipeline: WebSocket => Claude => iMessage")
    print(f"\nWebSocket URL: {websocket_url}")
    print("Model: claude-sonnet-4-6")
    print("\nMessages from the WebSocket will be processed by Claude,")
    print("and Claude's responses will be sent via iMessage.\n")

    # Create WebSocket input provider
    ws_provider = WebSocketTextInputProvider(url=websocket_url)

    # Create iMessage output handler
    imessage_handler = create_imessage_handler()

    # Create Claude output block with iMessage handler
    # persistent_context=True maintains conversation history across messages
    claude_block = ClaudeOutputBlock(
        output_handler=imessage_handler,
        system_prompt="You are Summer, a helpful AI assistant. Keep responses concise and friendly.",
        model="claude-sonnet-4-6",
        max_tokens=1024,
        persistent_context=True  # Maintains conversation history
    )

    # Connect WebSocket to Claude (which outputs to iMessage)
    ws_provider.connect_output_block(claude_block)

    # Start the pipeline
    print("Pipeline started! Listening for messages...\n")
    ws_provider.start()

    # Wait for the WebSocket connection (blocks until interrupted)
    try:
        ws_provider.wait()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        ws_provider.stop()
        print("Goodbye!")


if __name__ == "__main__":
    main()
