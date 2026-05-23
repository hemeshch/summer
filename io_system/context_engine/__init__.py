"""Summer's background context engine.

Ingests signals from the user's day (conversations, calendar, email), uses
Claude to extract explicit facts and inferred patterns, stores them in a
semantic index, and exposes a search() API so the agent can query its own
memory by meaning, not by keyword.
"""

from .embedder import (
    Embedder,
    OpenAIEmbedder,
    SentenceTransformersEmbedder,
    build_default_embedder,
)
from .engine import ContextEngine, IngestReport
from .extractor import FactExtractor
from .fact_store import Fact, FactStore
from .sources import (
    AppleCalendarSource,
    ConversationLogSource,
    DataSource,
    EmailSource,
    RawDocument,
)

__all__ = [
    "Embedder",
    "SentenceTransformersEmbedder",
    "OpenAIEmbedder",
    "build_default_embedder",
    "Fact",
    "FactStore",
    "FactExtractor",
    "ContextEngine",
    "IngestReport",
    "DataSource",
    "RawDocument",
    "ConversationLogSource",
    "AppleCalendarSource",
    "EmailSource",
]
