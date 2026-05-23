"""
iMessage Output Handler

Provides an output handler that sends outputs via iMessage using Apple Shortcuts.
"""

import os
import subprocess
from pathlib import Path
from io_system.base import Output
from io_system.outputs import TextMessageOutput


def _default_ipc_file() -> str:
    """Default IPC file lives next to the repo under shortcuts-ipc/in.txt.

    Override with the SUMMER_IPC_FILE environment variable when your Shortcut
    points somewhere else.
    """
    env = os.environ.get("SUMMER_IPC_FILE")
    if env:
        return env
    repo_root = Path(__file__).resolve().parents[2]
    return str(repo_root / "shortcuts-ipc" / "in.txt")


def create_imessage_handler(
    ipc_file: str = None,
    shortcut_name: str = "sendmessage"
):
    """
    Create an output handler that sends messages via iMessage.

    Args:
        ipc_file: Path to the IPC file to write messages to
        shortcut_name: Name of the Apple Shortcut to run

    Returns:
        A handler function that can be passed to OutputBlock constructors

    Example:
        from io_system import IdentityOutputBlock
        from io_system.handlers import create_imessage_handler

        handler = create_imessage_handler()
        block = IdentityOutputBlock(output_handler=handler)
    """
    ipc_path = Path(ipc_file or _default_ipc_file())
    ipc_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[iMessageHandler] Initialized")
    print(f"  IPC file: {ipc_path}")
    print(f"  Shortcut: {shortcut_name}")

    def handler(output_obj: Output):
        """
        Handler function that sends outputs via iMessage.

        Args:
            output_obj: The output to send
        """
        # Extract text from output
        if isinstance(output_obj, TextMessageOutput):
            message = output_obj.text
        elif hasattr(output_obj, 'text'):
            message = output_obj.text
        elif hasattr(output_obj, 'message'):
            message = output_obj.message
        else:
            # Fallback to string representation
            message = str(output_obj)

        try:
            # Step 1: Write message to IPC file
            print(f"[iMessageHandler] Writing to {ipc_path}")
            with open(ipc_path, 'w') as f:
                f.write(message)

            # Step 2: Run the shortcut
            print(f"[iMessageHandler] Running shortcut '{shortcut_name}'")
            result = subprocess.run(
                ["shortcuts", "run", shortcut_name],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                print(f"[iMessageHandler] Message sent successfully: {message}")
            else:
                error_msg = f"Shortcut failed: {result.stderr}"
                print(f"[iMessageHandler] {error_msg}")

        except subprocess.TimeoutExpired:
            print(f"[iMessageHandler] Shortcut execution timed out")

        except FileNotFoundError:
            print(f"[iMessageHandler] shortcuts command not found - make sure you're on macOS")

        except Exception as e:
            print(f"[iMessageHandler] Unexpected error: {e}")

    return handler
