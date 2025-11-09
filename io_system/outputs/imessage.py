"""
iMessage Output Type
"""

from io_system.base import Output


class iMessageOutput(Output):
    """iMessage output - represents a message to be sent via iMessage"""

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def get_type(self) -> str:
        return "imessage"

    def __repr__(self):
        return f"iMessageOutput(message='{self.message}', timestamp={self.timestamp})"
