"""
Identity Output Block
"""

from io_system.base import OutputBlock, Input
from io_system.inputs import TextMessageInput
from io_system.outputs import TextMessageOutput


class IdentityOutputBlock(OutputBlock):
    """
    POC output block that acts as an identity function.

    For each TextMessageInput, it produces an identical TextMessageOutput.
    """

    def __init__(self, output_handler=None):
        # Override default handler to show text nicely
        if output_handler is None:
            output_handler = self._text_default_handler
        super().__init__(output_handler)

    def _text_default_handler(self, output_obj):
        """Default handler that shows text outputs nicely"""
        if isinstance(output_obj, TextMessageOutput):
            print(f"[OUTPUT] {output_obj.text}")
        else:
            print(f"[OUTPUT] {output_obj}")

    def process_input(self, input_obj: Input):
        """Process input and produce corresponding output"""
        if isinstance(input_obj, TextMessageInput):
            output = TextMessageOutput(input_obj.text)
            self.emit_output(output)
        else:
            print(f"[IdentityOutputBlock] Received unknown input type: {input_obj.get_type()}")
