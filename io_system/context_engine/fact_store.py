"""Semantic fact store.

Sqlite for durability, in-memory cosine similarity for retrieval. Brute-force
search is fine up to ~100k facts; at that scale the model takes longer than
the search. When we need to scale past it, swap in FAISS or pgvector behind
this same interface.

Facts are deduplicated on insert by cosine similarity against existing facts —
above ``dedupe_threshold`` we update the existing row (bumping confidence and
recording another source ref) instead of inserting a duplicate.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from .embedder import Embedder


SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    embedding TEXT NOT NULL,           -- JSON array of floats
    embedding_dim INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'fact', -- fact | pattern | preference
    confidence REAL NOT NULL DEFAULT 0.7,
    source_refs TEXT NOT NULL DEFAULT '[]',  -- JSON list of strings
    metadata TEXT NOT NULL DEFAULT '{}',     -- JSON dict
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind);
"""


@dataclass
class Fact:
    text: str
    kind: str = "fact"  # fact | pattern | preference
    confidence: float = 0.7
    source_refs: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    score: Optional[float] = None  # populated by search()

    def to_display(self) -> str:
        tag = self.kind.upper()
        return f"[{tag}] {self.text}"


def _cosine(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class FactStore:
    def __init__(self, db_path: str, embedder: Embedder, dedupe_threshold: float = 0.92):
        self.db_path = str(db_path)
        self.embedder = embedder
        self.dedupe_threshold = dedupe_threshold
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    # ----- writes -----

    def add_many(self, facts: Iterable[Fact]) -> List[Fact]:
        """Insert facts, deduping against near-duplicates. Returns the facts
        as they ended up in the store (with id populated)."""
        facts = list(facts)
        if not facts:
            return []
        embeddings = self.embedder.embed([f.text for f in facts])
        existing = self._load_all_embeddings()
        results: List[Fact] = []
        for fact, vec in zip(facts, embeddings):
            dup_id, dup_score = self._find_duplicate(vec, existing)
            if dup_id is not None:
                self._merge_into(dup_id, fact)
                fact.id = dup_id
                fact.score = dup_score
            else:
                fact.id = self._insert(fact, vec)
                existing.append((fact.id, vec))
            results.append(fact)
        return results

    def add(self, fact: Fact) -> Fact:
        return self.add_many([fact])[0]

    def _insert(self, fact: Fact, embedding: List[float]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO facts (text, embedding, embedding_dim, kind, confidence, "
                "source_refs, metadata, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fact.text,
                    json.dumps(embedding),
                    len(embedding),
                    fact.kind,
                    fact.confidence,
                    json.dumps(fact.source_refs),
                    json.dumps(fact.metadata),
                    now,
                    now,
                ),
            )
            return cur.lastrowid

    def _merge_into(self, fact_id: int, incoming: Fact) -> None:
        """Bump confidence and merge source_refs into an existing fact."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT confidence, source_refs FROM facts WHERE id = ?", (fact_id,)
            ).fetchone()
            if row is None:
                return
            old_conf = row["confidence"]
            old_refs = set(json.loads(row["source_refs"]) or [])
            merged_refs = sorted(old_refs.union(incoming.source_refs))
            # Each corroboration bumps confidence toward 1.0 (geometric, capped).
            new_conf = min(1.0, 1.0 - (1.0 - old_conf) * (1.0 - incoming.confidence))
            conn.execute(
                "UPDATE facts SET confidence = ?, source_refs = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    new_conf,
                    json.dumps(merged_refs),
                    datetime.now(timezone.utc).isoformat(),
                    fact_id,
                ),
            )

    # ----- reads / search -----

    def _load_all_embeddings(self) -> List[tuple]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, embedding FROM facts").fetchall()
            return [(r["id"], json.loads(r["embedding"])) for r in rows]

    def _find_duplicate(
        self, vec: List[float], existing: List[tuple]
    ) -> tuple:
        best_id = None
        best_score = -1.0
        for fid, evec in existing:
            score = _cosine(vec, evec)
            if score > best_score:
                best_score = score
                best_id = fid
        if best_id is not None and best_score >= self.dedupe_threshold:
            return best_id, best_score
        return None, best_score

    def search(self, query: str, top_k: int = 5, min_score: float = 0.0) -> List[Fact]:
        if not query.strip():
            return []
        query_vec = self.embedder.embed([query])[0]
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM facts").fetchall()
        scored = []
        for row in rows:
            evec = json.loads(row["embedding"])
            score = _cosine(query_vec, evec)
            if score < min_score:
                continue
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        results: List[Fact] = []
        for score, row in scored[:top_k]:
            results.append(
                Fact(
                    id=row["id"],
                    text=row["text"],
                    kind=row["kind"],
                    confidence=row["confidence"],
                    source_refs=json.loads(row["source_refs"]),
                    metadata=json.loads(row["metadata"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    score=score,
                )
            )
        return results

    def all_facts(self) -> List[Fact]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM facts ORDER BY updated_at DESC"
            ).fetchall()
        return [
            Fact(
                id=row["id"],
                text=row["text"],
                kind=row["kind"],
                confidence=row["confidence"],
                source_refs=json.loads(row["source_refs"]),
                metadata=json.loads(row["metadata"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
