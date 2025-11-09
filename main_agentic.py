#!/usr/bin/env python3
"""
Stella Agentic - WebSocket to Agentic Claude to iMessage Pipeline

This is an enhanced version of Stella that uses the agentic Claude output block
with full tool support (file system, bash, zsh, etc.).

Setup required:
  - Add ANTHROPIC_API_KEY to .env
  - Create "sendmessage" shortcut in macOS Shortcuts (see shortcuts-ipc/README.md)
"""

from io_system import WebSocketTextInputProvider, AgenticClaudeOutputBlock
from io_system.handlers import create_imessage_handler


def main():
    print("=== Stella Agentic I/O System ===")
    print("\nPipeline: WebSocket => Agentic Claude (with tools) => iMessage")
    print("\nWebSocket URL: wss://channel-api.hemeshchadalavada.workers.dev/channels/stella")
    print("Model: claude-sonnet-4-5")
    print("Tools: File System, Bash, Zsh")
    print("\nMessages from the WebSocket will be processed by Claude with tool support,")
    print("and Claude's responses will be sent via iMessage.\n")

    # Create WebSocket input provider
    ws_provider = WebSocketTextInputProvider(
        url="wss://channel-api.hemeshchadalavada.workers.dev/channels/stella"
    )

    # Create iMessage output handler
    imessage_handler = create_imessage_handler()

    # Create Agentic Claude output block with iMessage handler
    agentic_claude_block = AgenticClaudeOutputBlock(
        output_handler=imessage_handler,
        system_prompt="""You are Stella, a helpful AI assistant with access to powerful tools.

You can:
- Read and write files on the system
- Execute bash commands
- List directory contents
- Perform complex multi-step tasks

When the user asks you to do something, think about what tools you need and use them.
Be proactive and helpful. Keep responses concise and friendly.""",
        model="claude-sonnet-4-5",
        max_tokens=4096,
        enabled_tools=['file_system', 'bash']  # Enable file system and bash tools
    )

    # Connect WebSocket to Agentic Claude (which outputs to iMessage)
    ws_provider.connect_output_block(agentic_claude_block)

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
