"""ContextEngine — orchestrates the daily ingestion pipeline.

Flow per run:
    1. For each registered source: fetch documents since last_ingest_at
    2. Send the combined doc batch to the FactExtractor (Claude)
    3. Insert the resulting Facts into the FactStore (which dedupes)
    4. Persist last_ingest_at so the next run picks up from there

State (last_ingest_at) is kept in a tiny JSON file next to the fact store.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .extractor import FactExtractor
from .fact_store import Fact, FactStore
from .sources.base import DataSource, RawDocument

logger = logging.getLogger(__name__)


@dataclass
class IngestReport:
    started_at: datetime
    finished_at: datetime
    docs_by_source: dict
    facts_added: int
    facts_total: int
    extractor_raw_response: str = ""

    def summary(self) -> str:
        by_src = ", ".join(f"{k}={v}" for k, v in self.docs_by_source.items()) or "(none)"
        return (
            f"Ingest finished in "
            f"{(self.finished_at - self.started_at).total_seconds():.1f}s. "
            f"Docs by source: {by_src}. "
            f"Facts added/total: {self.facts_added}/{self.facts_total}."
        )


class ContextEngine:
    def __init__(
        self,
        sources: List[DataSource],
        extractor: FactExtractor,
        store: FactStore,
        state_path: Optional[str] = None,
    ):
        self.sources = sources
        self.extractor = extractor
        self.store = store
        # Default state file sits next to the fact store DB.
        if state_path is None:
            state_path = str(Path(store.db_path).with_suffix(".state.json"))
        self.state_path = state_path

    # ----- state -----

    def _load_state(self) -> dict:
        p = Path(self.state_path)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_state(self, state: dict) -> None:
        Path(self.state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.state_path).write_text(json.dumps(state, indent=2), encoding="utf-8")

    def last_ingest_at(self) -> Optional[datetime]:
        raw = self._load_state().get("last_ingest_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            return None

    # ----- the actual run -----

    def run_daily_ingest(self, since: Optional[datetime] = None) -> IngestReport:
        started = datetime.now(timezone.utc)
        if since is None:
            since = self.last_ingest_at()
        logger.info("[ContextEngine] starting ingest; since=%s", since)

        all_docs: List[RawDocument] = []
        per_source: dict = {}
        for source in self.sources:
            try:
                docs = source.fetch_since(since)
            except Exception as e:
                logger.exception("[ContextEngine] source %r failed: %s", source.name, e)
                docs = []
            per_source[source.name] = len(docs)
            logger.info("[ContextEngine]   source=%s docs=%d", source.name, len(docs))
            all_docs.extend(docs)

        raw_response = ""
        facts: List[Fact] = []
        if all_docs:
            result = self.extractor.extract(all_docs)
            facts = result.facts
            raw_response = result.raw_response
            logger.info("[ContextEngine] extractor returned %d facts", len(facts))
            if facts:
                self.store.add_many(facts)

        finished = datetime.now(timezone.utc)
        # Persist the new high-water mark.
        self._save_state({"last_ingest_at": finished.isoformat()})

        return IngestReport(
            started_at=started,
            finished_at=finished,
            docs_by_source=per_source,
            facts_added=len(facts),
            facts_total=self.store.count(),
            extractor_raw_response=raw_response,
        )
