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

    Supports persistent context (conversation history) to maintain continuity
    across multiple messages.
    """

    def __init__(
        self,
        output_handler=None,
        system_prompt: Optional[str] = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 1024,
        api_key: Optional[str] = None,
        persistent_context: bool = True
    ):
        """
        Initialize Claude output block.

        Args:
            output_handler: Optional handler function for outputs
            system_prompt: System prompt to guide Claude's behavior
            model: Claude model to use (default: claude-sonnet-4-6)
            max_tokens: Maximum tokens in response (default: 1024)
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            persistent_context: If True, maintain conversation history across messages (default: True)
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
        self.persistent_context = persistent_context

        # Conversation history for persistent context
        self.conversation_history = []

        context_status = "enabled" if persistent_context else "disabled"
        print(f"[ClaudeOutputBlock] Initialized with model: {self.model}, persistent context: {context_status}")

    def process_input(self, input_obj: Input):
        """Process input and produce Claude's response as output"""
        if not isinstance(input_obj, TextMessageInput):
            print(f"[ClaudeOutputBlock] Received unknown input type: {input_obj.get_type()}")
            return

        user_message = input_obj.text

        try:
            print(f"[ClaudeOutputBlock] Sending to Claude: {user_message}")

            # Build messages list
            if self.persistent_context:
                # Add new user message to history
                self.conversation_history.append({
                    "role": "user",
                    "content": user_message
                })
                messages = self.conversation_history
            else:
                # One-shot message without history
                messages = [{"role": "user", "content": user_message}]

            # Call Claude API
            message = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=messages
            )

            # Extract response text
            response_text = message.content[0].text

            # Add assistant response to history if persistent context is enabled
            if self.persistent_context:
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response_text
                })

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

    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []
        print("[ClaudeOutputBlock] Conversation history cleared")

    def get_history_length(self) -> int:
        """Get the number of messages in conversation history."""
        return len(self.conversation_history)

    def get_history(self) -> list:
        """Get a copy of the conversation history."""
        return self.conversation_history.copy()
