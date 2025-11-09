"""
Output Blocks Package

Import all output blocks here for convenient access.
"""

from io_system.blocks.identity import IdentityOutputBlock
from io_system.blocks.claude import ClaudeOutputBlock
from io_system.blocks.agentic_claude import AgenticClaudeOutputBlock

__all__ = ['IdentityOutputBlock', 'ClaudeOutputBlock', 'AgenticClaudeOutputBlock']
