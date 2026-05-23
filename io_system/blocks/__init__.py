"""Output blocks. Each block is imported tolerantly so a missing optional
dependency doesn't break the entire package.
"""

import warnings

from io_system.blocks.identity import IdentityOutputBlock

__all__ = ["IdentityOutputBlock"]

try:
    from io_system.blocks.claude import ClaudeOutputBlock  # noqa: F401
    __all__.append("ClaudeOutputBlock")
except ImportError as e:
    warnings.warn(f"ClaudeOutputBlock unavailable: {e}", ImportWarning)

try:
    from io_system.blocks.agentic_claude import AgenticClaudeOutputBlock  # noqa: F401
    __all__.append("AgenticClaudeOutputBlock")
except ImportError as e:
    warnings.warn(f"AgenticClaudeOutputBlock unavailable: {e}", ImportWarning)
