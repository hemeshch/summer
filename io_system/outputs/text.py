"""
Text Output Types
"""

from io_system.base import Output


class TextMessageOutput(Output):
    """Text output message"""

    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def get_type(self) -> str:
        return "text_message"

    def __repr__(self):
        return f"TextMessageOutput(text='{self.text}', timestamp={self.timestamp})"
