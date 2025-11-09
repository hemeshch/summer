"""
Claude LLM Output Block
"""

import os
from typing import Optional
from dotenv import load_dotenv
import anthropic

from io_system.base import OutputBlock, Input
from io_system.inputs import TextMessageInput
from io_system.outputs import TextMessageOutput


# Load environment variables from .env file
load_dotenv()


class ClaudeOutputBlock(OutputBlock):
    """
    Output block that processes inputs through Claude AI.

    Takes TextMessageInput, sends it to Claude API, and outputs the response
    as TextMessageOutput.
    """

    def __init__(
        self,
        output_handler=None,
        system_prompt: Optional[str] = None,
        model: str = "claude-sonnet-4-5",
        max_tokens: int = 1024,
        api_key: Optional[str] = None
    ):
        """
        Initialize Claude output block.

        Args:
            output_handler: Optional handler function for outputs
            system_prompt: System prompt to guide Claude's behavior
            model: Claude model to use (default: claude-sonnet-4-5)
            max_tokens: Maximum tokens in response (default: 1024)
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        super().__init__(output_handler)

        # Get API key from parameter or environment
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY must be set in environment or passed as parameter. "
                "Add it to your .env file or export it in your shell."
            )

        # Initialize Claude client
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt or "You are a helpful AI assistant."

        print(f"[ClaudeOutputBlock] Initialized with model: {self.model}")

    def process_input(self, input_obj: Input):
        """Process input and produce Claude's response as output"""
        if not isinstance(input_obj, TextMessageInput):
            print(f"[ClaudeOutputBlock] Received unknown input type: {input_obj.get_type()}")
            return

        user_message = input_obj.text

        try:
            print(f"[ClaudeOutputBlock] Sending to Claude: {user_message}")

            # Call Claude API
            message = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            )

            # Extract response text
            response_text = message.content[0].text

            # Emit output
            output = TextMessageOutput(response_text)
            self.emit_output(output)

        except anthropic.APIError as e:
            error_msg = f"Claude API error: {e}"
            print(f"[ClaudeOutputBlock] {error_msg}")
            self.emit_output(TextMessageOutput(f"Error: {error_msg}"))

        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            print(f"[ClaudeOutputBlock] {error_msg}")
            self.emit_output(TextMessageOutput(f"Error: {error_msg}"))
