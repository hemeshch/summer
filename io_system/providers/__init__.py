"""
Input Providers Package

Import all input providers here for convenient access.
"""

from io_system.providers.stdin import StdinInputProvider
from io_system.providers.websocket import WebSocketTextInputProvider

__all__ = ['StdinInputProvider', 'WebSocketTextInputProvider']
