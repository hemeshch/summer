"""
Agentic Claude Output Block

An output block that processes inputs through Claude AI with tool support.
Uses the agent infrastructure from agent/stellagent_client for sophisticated tool calling.
"""

import os
import sys
from pathlib import Path
from typing import Optional, Callable, Any

# Add agent directory to path
agent_dir = Path(__file__).parent.parent.parent / "agent"
sys.path.insert(0, str(agent_dir))

from io_system.base import OutputBlock, Input, Output
from io_system.inputs import TextMessageInput
from io_system.outputs import TextMessageOutput

# Import agent infrastructure
from stellagent_client.claude_agent import ClaudeAgent
from stellagent_client.tool_system import ToolManager
from stellagent_client.tools import (
    FileSystemToolProvider,
    BashToolProvider,
    ZshToolProvider,
)


class AgenticClaudeOutputBlock(OutputBlock):
    """
    An output block that processes text inputs through Claude AI with tool support.

    Features:
    - Full Claude API integration with streaming
    - Tool calling capabilities (file system, bash, zsh, etc.)
    - Conversation history management
    - Configurable system prompt and model

    Example:
        block = AgenticClaudeOutputBlock(
            output_handler=my_handler,
            system_prompt="You are a helpful assistant with access to tools.",
            enabled_tools=['file_system', 'bash']
        )
    """

    def __init__(
        self,
        output_handler: Optional[Callable[[Output], None]] = None,
        system_prompt: Optional[str] = None,
        model: str = "claude-sonnet-4-5",
        max_tokens: int = 4096,
        enabled_tools: Optional[list] = None,
        runtime_dir: Optional[str] = None
    ):
        """
        Initialize the agentic Claude output block.

        Args:
            output_handler: Function to handle outputs (e.g., send to iMessage)
            system_prompt: System prompt for Claude
            model: Claude model to use
            max_tokens: Maximum tokens in response
            enabled_tools: List of tool names to enable (e.g., ['file_system', 'bash'])
            runtime_dir: Runtime directory for agent state and files
        """
        super().__init__(output_handler)

        # Set up runtime directory
        if runtime_dir is None:
            runtime_dir = str(Path(__file__).parent.parent.parent / "stella_runtime")
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Claude agent
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set in environment")

        self.claude_agent = ClaudeAgent(
            api_key=api_key,
            workspace_dir=str(self.runtime_dir),
            runtime_dir=str(self.runtime_dir)
        )
        self.claude_agent.set_model(model)
        self.claude_agent.set_max_tokens(max_tokens)

        # Override system prompt if provided
        if system_prompt:
            self.claude_agent.system_prompt = system_prompt

        # Initialize tool manager
        self.tool_manager = ToolManager()

        # Set up tools
        self.enabled_tools = enabled_tools or []
        self._setup_tools()

        # Conversation history (single conversation for now)
        self.conversation_history = []
        self.conversation_id = "stella-main"

        print(f"[AgenticClaudeOutputBlock] Initialized with model: {model}")
        print(f"[AgenticClaudeOutputBlock] Enabled tools: {self.enabled_tools}")
        print(f"[AgenticClaudeOutputBlock] Runtime directory: {self.runtime_dir}")

    def _setup_tools(self):
        """Set up and register enabled tools."""
        tool_providers = {
            'file_system': FileSystemToolProvider,
            'bash': BashToolProvider,
            'zsh': ZshToolProvider,
        }

        for tool_name in self.enabled_tools:
            if tool_name in tool_providers:
                try:
                    provider_class = tool_providers[tool_name]
                    provider = provider_class(websocket_handler=None)
                    self.tool_manager.register_provider(provider)
                    print(f"[AgenticClaudeOutputBlock] Registered tool: {tool_name}")
                except Exception as e:
                    print(f"[AgenticClaudeOutputBlock] Failed to register tool {tool_name}: {e}")
            else:
                print(f"[AgenticClaudeOutputBlock] Unknown tool: {tool_name}")

    def process_input(self, input_obj: Input):
        """
        Process an input through Claude with tool support.

        Args:
            input_obj: Input object to process
        """
        if not isinstance(input_obj, TextMessageInput):
            print(f"[AgenticClaudeOutputBlock] Ignoring non-text input: {type(input_obj)}")
            return

        user_message = input_obj.text
        print(f"\n[AgenticClaudeOutputBlock] Processing: {user_message[:100]}...")

        try:
            # Get tools in Anthropic format
            tools = self.tool_manager.get_anthropic_tools() if self.enabled_tools else []

            # Create tool callback
            def tool_callback(tool_id: str, parameters: dict):
                """Callback for tool execution."""
                print(f"[AgenticClaudeOutputBlock] Executing tool: {tool_id}")
                print(f"[AgenticClaudeOutputBlock] Parameters: {parameters}")

                # Execute the tool
                result, error = self.tool_manager.call_tool(
                    tool_id,
                    parameters,
                    self.conversation_id,
                    working_directory=str(self.runtime_dir)
                )

                if error:
                    print(f"[AgenticClaudeOutputBlock] Tool error: {error}")
                else:
                    print(f"[AgenticClaudeOutputBlock] Tool result: {str(result)[:200]}...")

                return result, error

            # Process prompt with Claude
            response, updated_history = self.claude_agent.process_prompt(
                prompt=user_message,
                conversation_history=self.conversation_history,
                tools=tools,
                tool_callback=tool_callback if self.enabled_tools else None,
                working_directory=str(self.runtime_dir)
            )

            # Update conversation history
            self.conversation_history = updated_history

            print(f"[AgenticClaudeOutputBlock] Response: {response[:100]}...")

            # Emit output
            if response:
                output = TextMessageOutput(response)
                self.emit_output(output)
            else:
                print("[AgenticClaudeOutputBlock] No response from Claude")

        except Exception as e:
            error_msg = f"Error processing input: {str(e)}"
            print(f"[AgenticClaudeOutputBlock] {error_msg}")
            # Emit error as output
            error_output = TextMessageOutput(f"Error: {error_msg}")
            self.emit_output(error_output)

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []
        print("[AgenticClaudeOutputBlock] Conversation history cleared")

    def get_history_length(self) -> int:
        """Get the number of messages in conversation history."""
        return len(self.conversation_history)
