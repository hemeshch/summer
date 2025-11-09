"""
WebSocket Input Provider
"""

import json
import websocket
import threading
from typing import Optional

from io_system.base import InputProvider
from io_system.inputs import TextMessageInput


class WebSocketTextInputProvider(InputProvider):
    """
    Input provider that subscribes to a WebSocket and produces TextMessageInput.

    Expects messages in JSON format: {"text": "message content"}
    """

    def __init__(self, url: str, auto_reconnect: bool = True):
        """
        Initialize WebSocket input provider.

        Args:
            url: WebSocket URL to connect to
            auto_reconnect: Whether to automatically reconnect on disconnect
        """
        super().__init__()
        self.url = url
        self.auto_reconnect = auto_reconnect
        self.running = False
        self.ws = None
        self._thread = None

        print(f"[WebSocketTextInputProvider] Initialized for URL: {url}")

    def start(self):
        """Start listening to the WebSocket"""
        self.running = True
        self._connect()

    def _connect(self):
        """Connect to the WebSocket and start receiving messages"""
        print(f"[WebSocketTextInputProvider] Connecting to {self.url}")

        # Create WebSocket connection
        self.ws = websocket.WebSocketApp(
            self.url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open
        )

        # Run in a separate thread
        self._thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self._thread.start()

    def _on_open(self, ws):
        """Called when WebSocket connection is opened"""
        print(f"[WebSocketTextInputProvider] Connected to {self.url}")

    def _on_message(self, ws, message):
        """
        Called when a message is received from the WebSocket.

        Args:
            ws: WebSocket instance
            message: Raw message string
        """
        try:
            # Parse JSON message
            data = json.loads(message)

            # Extract text field
            if "text" in data:
                text = data["text"]
                print(f"[WebSocketTextInputProvider] Received: {text}")

                # Create input and notify output blocks
                text_input = TextMessageInput(text)
                self.notify_output_blocks(text_input)
            else:
                print(f"[WebSocketTextInputProvider] Warning: Message missing 'text' field: {message}")

        except json.JSONDecodeError as e:
            print(f"[WebSocketTextInputProvider] Error: Failed to parse JSON: {e}")
            print(f"  Raw message: {message}")

        except Exception as e:
            print(f"[WebSocketTextInputProvider] Error processing message: {e}")

    def _on_error(self, ws, error):
        """Called when a WebSocket error occurs"""
        print(f"[WebSocketTextInputProvider] WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """Called when WebSocket connection is closed"""
        print(f"[WebSocketTextInputProvider] Connection closed")
        if close_status_code:
            print(f"  Status code: {close_status_code}")
        if close_msg:
            print(f"  Message: {close_msg}")

        # Auto-reconnect if enabled and still running
        if self.auto_reconnect and self.running:
            print("[WebSocketTextInputProvider] Attempting to reconnect in 5 seconds...")
            import time
            time.sleep(5)
            if self.running:
                self._connect()

    def stop(self):
        """Stop the WebSocket connection"""
        print("[WebSocketTextInputProvider] Stopping...")
        self.running = False
        if self.ws:
            self.ws.close()

    def wait(self):
        """Wait for the WebSocket thread to finish (blocking)"""
        if self._thread:
            try:
                self._thread.join()
            except KeyboardInterrupt:
                print("\n[WebSocketTextInputProvider] Interrupted")
                self.stop()
