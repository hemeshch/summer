"""DataSource abstraction.

A source produces RawDocuments. Documents have a timestamp so the engine can
diff against last-ingested-at. doc_id is opaque but stable per document so
we can attribute facts back to the signals they came from.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class RawDocument:
    source: str  # "conversation" | "calendar" | "email" | ...
    content: str
    timestamp: Optional[datetime] = None
    doc_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class DataSource(ABC):
    """A source of RawDocuments. Implementations should be cheap to construct
    and only do I/O inside fetch_since.
    """

    name: str = "unnamed"

    @abstractmethod
    def fetch_since(self, since: Optional[datetime]) -> List[RawDocument]:
        """Return all documents with timestamp >= since (or all of them if
        since is None). Implementations should be safe to call multiple
        times — the engine handles dedupe at the fact layer.
        """
        ...
