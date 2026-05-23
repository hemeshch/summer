"""Conversation source — reads JSONL chat logs written by the agent block.

Each line of the log is a JSON object:
    {"timestamp": "2026-05-22T20:13:45+00:00",
     "role": "user" | "assistant",
     "text": "..."}

The source bundles consecutive lines into a single conversation "turn" doc
so the extractor sees user message + assistant response together.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .base import DataSource, RawDocument


class ConversationLogSource(DataSource):
    name = "conversation"

    def __init__(self, log_path: str):
        self.log_path = Path(log_path)

    def fetch_since(self, since: Optional[datetime]) -> List[RawDocument]:
        if not self.log_path.exists():
            return []

        # Group lines into turn-pairs (user → assistant). Anything that doesn't
        # pair cleanly is emitted on its own; the extractor handles partial
        # context fine.
        entries = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = self._parse_ts(entry.get("timestamp"))
            if since is not None and ts is not None and ts < since:
                continue
            entries.append((ts, entry))

        docs: List[RawDocument] = []
        i = 0
        while i < len(entries):
            ts, entry = entries[i]
            role = entry.get("role", "?")
            text = entry.get("text", "")
            if role == "user" and i + 1 < len(entries) and entries[i + 1][1].get("role") == "assistant":
                next_ts, next_entry = entries[i + 1]
                content = f"USER: {text}\nASSISTANT: {next_entry.get('text', '')}"
                docs.append(
                    RawDocument(
                        source=self.name,
                        content=content,
                        timestamp=ts or next_ts,
                        doc_id=f"conv:{(ts or next_ts).isoformat() if (ts or next_ts) else i}",
                    )
                )
                i += 2
            else:
                docs.append(
                    RawDocument(
                        source=self.name,
                        content=f"{role.upper()}: {text}",
                        timestamp=ts,
                        doc_id=f"conv:{ts.isoformat() if ts else i}",
                    )
                )
                i += 1
        return docs

    @staticmethod
    def _parse_ts(value) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
