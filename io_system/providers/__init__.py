"""Input providers. Imported tolerantly so missing optional deps don't
break the whole package.
"""

import warnings

from io_system.providers.stdin import StdinInputProvider

__all__ = ["StdinInputProvider"]

try:
    from io_system.providers.websocket import WebSocketTextInputProvider  # noqa: F401
    __all__.append("WebSocketTextInputProvider")
except ImportError as e:
    warnings.warn(f"WebSocketTextInputProvider unavailable: {e}", ImportWarning)
