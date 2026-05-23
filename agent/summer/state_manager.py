import os
import json
import copy
from typing import Any, Dict
from pathlib import Path
import threading


class StateManager:
    """Manages persistent state for tools and conversations."""

    def __init__(self, runtime_dir: str = "summer_runtime", reset_state: bool = False):
        self.runtime_dir = Path(runtime_dir)
        self.state_file = self.runtime_dir / "tool_states.json"
        self.legacy_pickle_file = self.runtime_dir / "tool_states.pkl"
        self.lock = threading.RLock()

        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        if reset_state:
            for f in (self.state_file, self.legacy_pickle_file):
                if f.exists():
                    os.remove(f)

        if self.legacy_pickle_file.exists():
            # Old format used pickle, which is unsafe to load. Discard it.
            print(
                f"Discarding legacy pickle state at {self.legacy_pickle_file} "
                "(unsafe to load); starting fresh."
            )
            try:
                os.remove(self.legacy_pickle_file)
            except OSError:
                pass

        self._load_state()

    def _load_state(self):
        """Load state from the JSON file."""
        with self.lock:
            if self.state_file.exists():
                try:
                    with open(self.state_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.global_state = data.get('global', {})
                        self.per_conversation_state = data.get('conversations', {})
                except (OSError, json.JSONDecodeError) as e:
                    print(f"Error loading state: {e}, initializing fresh state")
                    self._initialize_state_locked()
            else:
                self._initialize_state_locked()

    def _initialize_state_locked(self):
        """Initialize fresh state. Caller must hold self.lock."""
        self.global_state = {}
        self.per_conversation_state = {}
        self._save_state_locked()

    def _save_state_locked(self):
        """Persist state to disk. Caller must hold self.lock."""
        data = {
            'global': self.global_state,
            'conversations': self.per_conversation_state,
        }
        tmp_path = self.state_file.with_suffix(self.state_file.suffix + '.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.replace(tmp_path, self.state_file)

    def get_global_state(self) -> Dict[str, Any]:
        """Return a deep copy of the global state dictionary."""
        with self.lock:
            return copy.deepcopy(self.global_state)

    def set_global_state(self, key: str, value: Any):
        """Set a value in global state."""
        with self.lock:
            self.global_state[key] = value
            self._save_state_locked()

    def get_conversation_state(self, conversation_id: str) -> Dict[str, Any]:
        """Return a deep copy of the conversation's state dictionary."""
        with self.lock:
            if conversation_id not in self.per_conversation_state:
                self.per_conversation_state[conversation_id] = {}
                self._save_state_locked()
            return copy.deepcopy(self.per_conversation_state[conversation_id])

    def set_conversation_state(self, conversation_id: str, key: str, value: Any):
        """Set a value in conversation-specific state."""
        with self.lock:
            if conversation_id not in self.per_conversation_state:
                self.per_conversation_state[conversation_id] = {}
            self.per_conversation_state[conversation_id][key] = value
            self._save_state_locked()

    def create_conversation(self, conversation_id: str):
        """Initialize state for a new conversation."""
        with self.lock:
            if conversation_id not in self.per_conversation_state:
                self.per_conversation_state[conversation_id] = {}
                self._save_state_locked()

    def remove_conversation(self, conversation_id: str):
        """Remove state for a conversation."""
        with self.lock:
            if conversation_id in self.per_conversation_state:
                del self.per_conversation_state[conversation_id]
                self._save_state_locked()

    def clear_all(self):
        """Clear all state and reinitialize."""
        with self.lock:
            self._initialize_state_locked()
