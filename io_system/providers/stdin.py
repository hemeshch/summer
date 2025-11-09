"""
Stdin Input Provider
"""

import sys
from io_system.base import InputProvider
from io_system.inputs import TextMessageInput


class StdinInputProvider(InputProvider):
    """Input provider that reads from stdin and produces TextMessageInput"""

    def __init__(self):
        super().__init__()
        self.running = False

    def start(self):
        """Start reading from stdin continuously"""
        self.running = True
        print("StdinInputProvider: Ready to receive input (Ctrl+C to stop)")

        try:
            while self.running:
                line = sys.stdin.readline()

                if not line:
                    break

                line = line.rstrip('\n')

                if line:
                    text_input = TextMessageInput(line)
                    self.notify_output_blocks(text_input)

        except KeyboardInterrupt:
            print("\nStdinInputProvider: Stopped")
            self.running = False

    def stop(self):
        """Stop the input provider"""
        self.running = False
