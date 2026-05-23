"""ZSH tool for executing commands in zsh on macOS."""

import subprocess
import os
from typing import Dict, List, Any, Optional, Tuple
from ..tool_system import BaseToolSetProvider, Tool, Parameter, ParameterType


class ZshToolProvider(BaseToolSetProvider):
    """ZSH tool provider for executing commands in a zsh shell."""

    def __init__(self, websocket_handler=None):
        super().__init__(websocket_handler)

    def init(self) -> Tuple[List[Tool], Dict[str, Any], Dict[str, Dict[str, Any]]]:
        """Initialize the zsh tool."""
        tools = [
            Tool(
                id="zsh",
                name="Execute ZSH Command",
                display_name="Execute Terminal Command",
                description="Execute a command in a zsh shell on the user's actual macOS system. Starts in the user's home directory. Has full access to the user's file system and macOS environment.",
                parameters={
                    "command": Parameter(
                        name="command",
                        type=ParameterType.STRING,
                        description="The zsh command to execute",
                        required=True,
                    ),
                    "timeout": Parameter(
                        name="timeout",
                        type=ParameterType.NUMBER,
                        description="Command timeout in seconds (0 to disable)",
                        required=False,
                        default=3.0,
                    ),
                },
            )
        ]
        return tools, {}, {}

    def call_tool(
        self,
        tool_id: str,
        tool_parameters: Dict[str, Any],
        per_conversation_state: Dict[str, Any],
        global_state: Dict[str, Any],
    ) -> Tuple[Any, Optional[str]]:
        """Execute tool calls."""
        try:
            if tool_id == "zsh":
                return self._execute_zsh(tool_parameters)
            return None, f"Unknown tool: {tool_id}"
        except Exception as e:
            return None, f"Error executing tool {tool_id}: {str(e)}"

    def _execute_zsh(self, parameters: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
        """Run a command via `zsh -c` in the user's home directory."""
        command = parameters["command"]
        timeout = parameters.get("timeout", 30.0)

        kwargs = {
            "capture_output": True,
            "text": True,
            "cwd": os.path.expanduser("~"),
        }
        if timeout > 0:
            kwargs["timeout"] = timeout

        try:
            result = subprocess.run(["/bin/zsh", "-c", command], **kwargs)
            return {
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "command": command,
                "session_active": False,
            }, None
        except subprocess.TimeoutExpired:
            return None, f"Command timed out after {timeout} seconds"
        except Exception as e:
            return None, f"Error executing command: {str(e)}"
