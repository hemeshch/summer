#!/usr/bin/env python3
"""
Stella - WebSocket to Claude to iMessage Pipeline

This is the main entry point for the Stella I/O system.
It creates a pipeline that:
  1. Receives messages from a WebSocket channel
  2. Processes them through Claude AI
  3. Sends Claude's responses via iMessage

Setup required:
  - Add ANTHROPIC_API_KEY to .env
  - Create "sendmessage" shortcut in macOS Shortcuts (see shortcuts-ipc/README.md)
"""

from io_system import WebSocketTextInputProvider, ClaudeOutputBlock
from io_system.handlers import create_imessage_handler


def main():
    print("=== Stella I/O System ===")
    print("\nPipeline: WebSocket => Claude => iMessage")
    print("\nWebSocket URL: wss://channel-api.hemeshchadalavada.workers.dev/channels/stella")
    print("Model: claude-sonnet-4-5")
    print("\nMessages from the WebSocket will be processed by Claude,")
    print("and Claude's responses will be sent via iMessage.\n")

    # Create WebSocket input provider
    ws_provider = WebSocketTextInputProvider(
        url="wss://channel-api.hemeshchadalavada.workers.dev/channels/stella"
    )

    # Create iMessage output handler
    imessage_handler = create_imessage_handler()

    # Create Claude output block with iMessage handler
    claude_block = ClaudeOutputBlock(
        output_handler=imessage_handler,
        system_prompt="You are Stella, a helpful AI assistant. Keep responses concise and friendly.",
        model="claude-sonnet-4-5",
        max_tokens=1024
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
