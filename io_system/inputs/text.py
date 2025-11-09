"""
Text Input Types
"""

from io_system.base import Input


class TextMessageInput(Input):
    """Text input message"""

    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def get_type(self) -> str:
        return "text_message"

    def __repr__(self):
        return f"TextMessageInput(text='{self.text}', timestamp={self.timestamp})"
