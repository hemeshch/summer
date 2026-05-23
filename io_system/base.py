"""
Rich Input/Output System - Base Classes

This module provides the base abstract classes for the I/O system:
- Input: Base class for all input types
- Output: Base class for all output types
- InputProvider: Base class for input providers that stream inputs
- OutputBlock: Base class for output blocks that process inputs
"""

from abc import ABC, abstractmethod
from typing import Optional, Callable
from datetime import datetime
import threading


class Input(ABC):
    """Base class for all input types"""

    def __init__(self):
        self.timestamp = datetime.now()

    @abstractmethod
    def get_type(self) -> str:
        """Return the type of input"""
        pass


class Output(ABC):
    """Base class for all output types"""

    def __init__(self):
        self.timestamp = datetime.now()

    @abstractmethod
    def get_type(self) -> str:
        """Return the type of output"""
        pass


class InputProvider(ABC):
    """Base class for input providers that stream inputs"""

    def __init__(self):
        self.output_blocks = []
        self._output_blocks_lock = threading.Lock()

    def connect_output_block(self, output_block: 'OutputBlock'):
        """Connect an output block to receive inputs from this provider"""
        with self._output_blocks_lock:
            self.output_blocks.append(output_block)

    def notify_output_blocks(self, input_obj: Input):
        """Notify all connected output blocks of a new input"""
        with self._output_blocks_lock:
            blocks = list(self.output_blocks)
        for block in blocks:
            block.notify_input(input_obj)

    @abstractmethod
    def start(self):
        """Start providing inputs"""
        pass


class OutputBlock(ABC):
    """
    Base class for output blocks.

    Output blocks:
    - Receive inputs via notify_input()
    - Can produce outputs via their handler
    - Inputs don't have to produce outputs
    - Outputs can be produced without inputs
    """

    def __init__(self, output_handler: Optional[Callable[[Output], None]] = None):
        """
        Initialize output block.

        Args:
            output_handler: Optional handler function to call when producing outputs.
                           If None, a default handler is used.
        """
        self.output_handler = output_handler or self._default_output_handler

    def _default_output_handler(self, output_obj: Output):
        """Default handler that prints outputs"""
        print(f"[OUTPUT] {output_obj}")

    def notify_input(self, input_obj: Input):
        """Called when a new input is received"""
        self.process_input(input_obj)

    @abstractmethod
    def process_input(self, input_obj: Input):
        """Process an input and optionally produce outputs"""
        pass

    def emit_output(self, output_obj: Output):
        """Emit an output through the handler"""
        self.output_handler(output_obj)

    def produce_output_without_input(self, output_obj: Output):
        """Produce an output without an input (spontaneous output)"""
        self.emit_output(output_obj)
