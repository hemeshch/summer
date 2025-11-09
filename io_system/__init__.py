"""
Rich Input/Output System

A flexible framework for handling various types of inputs and outputs
with a streaming, event-driven architecture.

Package structure:
- base: Base abstract classes (Input, Output, InputProvider, OutputBlock)
- inputs: Concrete input types
- outputs: Concrete output types
- providers: Input provider implementations
- blocks: Output block implementations
- handlers: Output handler functions (for delivery mechanisms like iMessage)
"""

# Export base classes
from io_system.base import Input, Output, InputProvider, OutputBlock

# Export concrete implementations for convenience
from io_system.inputs import *
from io_system.outputs import *
from io_system.providers import *
from io_system.blocks import *

__version__ = '0.1.0'

__all__ = [
    # Base classes
    'Input',
    'Output',
    'InputProvider',
    'OutputBlock',
    # Concrete types (from subpackages)
    'TextMessageInput',
    'TextMessageOutput',
    'iMessageOutput',
    'StdinInputProvider',
    'WebSocketTextInputProvider',
    'IdentityOutputBlock',
    'ClaudeOutputBlock',
]
