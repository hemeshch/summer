"""Calendar source — pulls upcoming events via the existing macOS Shortcuts
get_calendar_events tool. Best-effort: if the shortcut isn't configured,
fetch_since returns []. Not a hard error.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .base import DataSource, RawDocument

logger = logging.getLogger(__name__)


class AppleCalendarSource(DataSource):
    """Reads events from Apple Calendar via the shortcut at
    SUMMER_SHORTCUTS_DIR/get_calendar_events.sh (or similar).

    The shortcut is expected to print JSON like:
        [{"title": "deep work",
          "start": "2026-05-22T22:00:00",
          "end":   "2026-05-23T03:00:00",
          "calendar": "Personal",
          "notes": "..."}]

    If anything fails (shortcut missing, not on macOS, parse error) the source
    returns [] rather than raising — calendar ingest is best-effort.
    """

    name = "calendar"

    def __init__(self, shortcut_name: str = "get_calendar_events", lookback_days: int = 1):
        self.shortcut_name = shortcut_name
        self.lookback_days = lookback_days

    def fetch_since(self, since: Optional[datetime]) -> List[RawDocument]:
        try:
            payload = self._run_shortcut(since)
        except Exception as e:
            logger.info("calendar source skipped: %s", e)
            return []

        if not payload:
            return []

        docs: List[RawDocument] = []
        for ev in payload:
            try:
                start = self._parse_ts(ev.get("start"))
            except Exception:
                start = None
            content = self._format_event(ev)
            docs.append(
                RawDocument(
                    source=self.name,
                    content=content,
                    timestamp=start,
                    doc_id=self._doc_id(ev, start),
                    metadata=ev,
                )
            )
        return docs

    def _run_shortcut(self, since: Optional[datetime]) -> Optional[list]:
        # Pass the lookback window via env var; the shortcut decides how to use it.
        env = os.environ.copy()
        env["SUMMER_CALENDAR_LOOKBACK_DAYS"] = str(self.lookback_days)
        result = subprocess.run(
            ["shortcuts", "run", self.shortcut_name],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Shortcut '{self.shortcut_name}' failed: {result.stderr.strip()}"
            )
        raw = result.stdout.strip()
        if not raw:
            return []
        return json.loads(raw)

    @staticmethod
    def _parse_ts(value) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _format_event(ev: dict) -> str:
        title = ev.get("title", "(untitled)")
        start = ev.get("start", "?")
        end = ev.get("end", "?")
        notes = ev.get("notes") or ""
        return f"Calendar event: '{title}' {start} → {end}. {notes}".strip()

    @staticmethod
    def _doc_id(ev: dict, start: Optional[datetime]) -> str:
        base = ev.get("title", "")
        ts = start.isoformat() if start else ""
        return f"cal:{ts}:{base}"
