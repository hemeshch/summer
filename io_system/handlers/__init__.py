"""
Output Handlers Package

Output handlers are functions that take Output objects and deliver/send them
somewhere (stdout, iMessage, file, network, etc.)
"""

from io_system.handlers.imessage import create_imessage_handler

__all__ = ['create_imessage_handler']
