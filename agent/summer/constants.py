"""Constants for SummerAgent Client.

URLs default to the values set by environment variables. Configure them in
your `.env` file (see `.env.example`).
"""
import os

# WebSocket endpoints
WEBSOCKET_SERVER_URL = os.environ.get(
    "WEBSOCKET_SERVER_URL",
    "wss://your-worker.workers.dev",
)
BROADCAST_API_URL = os.environ.get(
    "BROADCAST_API_URL",
    "https://your-worker.workers.dev/broadcast",
)

# File upload service
FILE_UPLOAD_API_URL = os.environ.get(
    "FILE_UPLOAD_API_URL",
    "https://your-file-upload-api.workers.dev/upload",
)

# Default configurations
DEFAULT_RUNTIME_DIR = "summer_runtime"
DEFAULT_CLAUDE_MODEL = "claude-opus-4-7"
BACKUP_CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 32000

# Retry configuration
MAX_BACKOFF_SECONDS = 3  # Maximum backoff duration
INITIAL_BACKOFF_SECONDS = 0.1  # Initial backoff duration
BACKOFF_MULTIPLIER = 2  # Exponential multiplier
FALLBACK_RETRY_COUNT = 10  # Number of retries before switching to backup model
# No limit to total retries - will keep retrying indefinitely