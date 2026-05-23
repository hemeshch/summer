"""Email source — stub.

Gmail integration requires OAuth + the Gmail API client + a token refresh
flow. That's a multi-day project and we'd rather ship the rest first. The
interface is here so the orchestrator can register a real EmailSource later
without any other code changing.

For now, fetch_since reads from an optional file at SUMMER_EMAIL_FIXTURE
(JSONL of email-shaped dicts) so demos can use canned data.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .base import DataSource, RawDocument


class EmailSource(DataSource):
    """File-backed email source. Real Gmail integration is TODO."""

    name = "email"

    def __init__(self, fixture_path: Optional[str] = None):
        env_fixture = os.environ.get("SUMMER_EMAIL_FIXTURE")
        self.fixture_path = Path(fixture_path or env_fixture) if (fixture_path or env_fixture) else None

    def fetch_since(self, since: Optional[datetime]) -> List[RawDocument]:
        if not self.fixture_path or not self.fixture_path.exists():
            return []
        docs: List[RawDocument] = []
        for line in self.fixture_path.read_text(encoding="utf-8").splitlines():
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
            content = (
                f"Email from {entry.get('from', '?')}\n"
                f"Subject: {entry.get('subject', '')}\n\n"
                f"{entry.get('body', '')}"
            )
            docs.append(
                RawDocument(
                    source=self.name,
                    content=content,
                    timestamp=ts,
                    doc_id=f"email:{entry.get('id') or ts}",
                    metadata=entry,
                )
            )
        return docs

    @staticmethod
    def _parse_ts(value) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
