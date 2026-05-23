"""
Agentic Claude Output Block

An output block that processes inputs through Claude AI with tool support.
Uses the agent infrastructure from agent/summer for sophisticated tool calling.
"""

import os
import sys
from pathlib import Path
from typing import Optional, Callable, Any

# Add agent directory to path
agent_dir = Path(__file__).parent.parent.parent / "agent"
sys.path.insert(0, str(agent_dir))

import json
from datetime import datetime, timezone

from io_system.base import OutputBlock, Input, Output
from io_system.inputs import TextMessageInput
from io_system.outputs import TextMessageOutput

# Import agent infrastructure
from summer.claude_agent import ClaudeAgent
from summer.tool_system import ToolManager
from summer.tools import (
    FileSystemToolProvider,
    BashToolProvider,
    ZshToolProvider,
)
from summer.tools.doordash_tool import DoorDashToolProvider
from summer.tools.memory_write_tool import MemoryWriteToolProvider
from summer.tools.proactive_tool import ProactiveSchedulerToolProvider
from summer.tools.recall_tool import RecallToolProvider


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
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        enabled_tools: Optional[list] = None,
        runtime_dir: Optional[str] = None,
        scheduler: Optional[Any] = None,
        fact_store: Optional[Any] = None,
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
            runtime_dir = str(Path(__file__).parent.parent.parent / "summer_runtime")
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
        self.scheduler = scheduler

        # Set up tools
        self.enabled_tools = enabled_tools or []
        self._setup_tools()

        # If a scheduler was provided, expose the proactive check-in tool to Claude.
        if self.scheduler is not None:
            self.tool_manager.register_provider(
                ProactiveSchedulerToolProvider(scheduler=self.scheduler)
            )
            print("[AgenticClaudeOutputBlock] Registered tool: schedule_proactive_check_in")

        # If a fact store was provided, expose semantic recall + write to Claude.
        self.fact_store = fact_store
        if self.fact_store is not None:
            self.tool_manager.register_provider(
                RecallToolProvider(fact_store=self.fact_store)
            )
            print("[AgenticClaudeOutputBlock] Registered tool: recall_relevant_facts")
            self.tool_manager.register_provider(
                MemoryWriteToolProvider(fact_store=self.fact_store)
            )
            print("[AgenticClaudeOutputBlock] Registered tool: add_fact_to_memory")

        # DoorDash stub. Hooked to fact_store so successful orders update memory.
        self.tool_manager.register_provider(
            DoorDashToolProvider(fact_store=self.fact_store)
        )
        print("[AgenticClaudeOutputBlock] Registered tool: place_doordash_order (stub)")

        # Conversation history (single conversation for now)
        self.conversation_history = []
        self.conversation_id = "summer-main"

        # JSONL conversation log so the context engine has real data to ingest.
        self.conversation_log_path = self.runtime_dir / "conversation_log.jsonl"

        print(f"[AgenticClaudeOutputBlock] Initialized with model: {model}")
        print(f"[AgenticClaudeOutputBlock] Enabled tools: {self.enabled_tools}")
        print(f"[AgenticClaudeOutputBlock] Runtime directory: {self.runtime_dir}")
        print(f"[AgenticClaudeOutputBlock] Conversation log: {self.conversation_log_path}")

    def _log_turn(self, role: str, text: str) -> None:
        """Append one role/text entry to the JSONL conversation log."""
        if not text:
            return
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "conversation_id": self.conversation_id,
            "role": role,
            "text": text,
        }
        try:
            with open(self.conversation_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            print(f"[AgenticClaudeOutputBlock] Failed to write conversation log: {e}")

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
        self._log_turn("user", user_message)

        try:
            # Pass every registered tool to Claude — proactive + recall don't
            # need to be listed in enabled_tools to be exposed.
            tools = self.tool_manager.get_anthropic_tools() if self.tool_manager.tools else []

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
                tool_callback=tool_callback if tools else None,
                working_directory=str(self.runtime_dir)
            )

            # Update conversation history
            self.conversation_history = updated_history

            print(f"[AgenticClaudeOutputBlock] Response: {response[:100]}...")

            # Emit output
            if response:
                self._log_turn("assistant", response)
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

    def process_proactive_check_in(self, context: str, conversation_id: Optional[str] = None) -> Optional[str]:
        """Run Claude as an unprompted check-in.

        Called by the ProactiveScheduler when a previously-scheduled check-in
        is due. ``context`` is the note the model wrote to its future self
        when scheduling. We hand it back as a synthetic prompt, run the agent
        loop (with tools), and route any non-SKIP response through the same
        output handler that real user messages use.

        Returns the response string that was emitted, or None if the model
        chose to SKIP.
        """
        local_now = datetime.now().strftime("%A %Y-%m-%d %H:%M %Z").strip()
        prompt = (
            "[Proactive check-in]\n"
            f"It is now {local_now}. Earlier in this conversation you scheduled this "
            "check-in to fire now. Here is the note you wrote to yourself:\n\n"
            f"{context}\n\n"
            "Decide whether to message the user right now. If you should message them, "
            "respond with the EXACT message you want sent — no preamble, no quotes, no "
            "explanation. If on reflection it would be intrusive or no longer relevant, "
            "respond with the single word: SKIP"
        )

        print(f"\n[AgenticClaudeOutputBlock] Proactive check-in firing")
        print(f"[AgenticClaudeOutputBlock] Context: {context[:120]}")

        tools = self.tool_manager.get_anthropic_tools() if self.tool_manager.tools else []

        def tool_callback(tool_id: str, parameters: dict):
            return self.tool_manager.call_tool(
                tool_id,
                parameters,
                conversation_id or self.conversation_id,
                working_directory=str(self.runtime_dir),
            )

        try:
            response, updated_history = self.claude_agent.process_prompt(
                prompt=prompt,
                conversation_history=self.conversation_history,
                tools=tools,
                tool_callback=tool_callback if tools else None,
                working_directory=str(self.runtime_dir),
            )
        except Exception as e:
            print(f"[AgenticClaudeOutputBlock] Proactive check-in errored: {e}")
            return None

        self.conversation_history = updated_history
        message = (response or "").strip()

        if not message or message.upper().startswith("SKIP"):
            print("[AgenticClaudeOutputBlock] Proactive check-in: model chose to SKIP")
            return None

        print(f"[AgenticClaudeOutputBlock] Proactive message: {message[:120]}")
        self._log_turn("assistant_proactive", message)
        self.emit_output(TextMessageOutput(message))
        return message

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []
        print("[AgenticClaudeOutputBlock] Conversation history cleared")

    def get_history_length(self) -> int:
        """Get the number of messages in conversation history."""
        return len(self.conversation_history)
