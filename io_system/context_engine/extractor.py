"""Fact extractor — Claude turns raw documents into structured facts.

Given a batch of RawDocuments (one day's conversation lines + calendar events
+ emails), we ask Claude to return both EXPLICIT facts the user stated and
INFERRED PATTERNS (e.g. recurring DoorDash receipts at 2am imply a 2am matcha
habit). The model returns JSON that we parse into Fact objects.

The extractor doesn't embed or dedupe — that's the FactStore's job. Here we
just turn unstructured text into structured rows.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from .fact_store import Fact
from .sources.base import RawDocument

logger = logging.getLogger(__name__)


EXTRACTION_SYSTEM = """You are the background context engine for Summer, a proactive personal AI agent.

Your job: read raw signals from the user's day (chat snippets, calendar events, email subjects/bodies) and return a JSON array of structured facts about the user. Two kinds:

1. EXPLICIT facts — things the user directly stated or that the data directly states (e.g. "user has a midterm in COMP 326 on 2026-05-23").
2. INFERRED PATTERNS — habits or preferences implied by recurring or contextual signals (e.g. recurring 2am Agora Coffee receipts → "user orders matcha latte from Agora Coffee around 2am during late-night work sessions").

For each fact, emit:
- "text": one self-contained sentence about the user. Concrete, not vague.
- "kind": "fact" (explicit) | "pattern" (inferred recurrence) | "preference" (stated or implied taste).
- "confidence": 0.5–1.0. Patterns from a single occurrence are ~0.6; explicit statements are ~0.9; well-corroborated recurrences are ~0.85+.

Rules:
- Skip trivia ("user said hi today"). Only emit facts worth remembering weeks later.
- Skip anything sensitive unless the user explicitly asked you to remember it.
- Prefer fewer high-signal facts to many noisy ones. 0–6 facts per batch is typical.
- Return ONLY a JSON array, no commentary. Empty array `[]` is fine."""


@dataclass
class ExtractionResult:
    facts: List[Fact]
    raw_response: str
    used_doc_ids: List[str]


class FactExtractor:
    """Calls Claude to turn raw docs into Fact objects."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 2048,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.max_tokens = max_tokens
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            if not self.api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY not set — cannot run fact extraction"
                )
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)

    def _format_docs(self, docs: List[RawDocument]) -> str:
        lines = []
        for d in docs:
            ts = d.timestamp.isoformat() if d.timestamp else "unknown-time"
            lines.append(f"[{d.source} @ {ts}] {d.content}")
        return "\n".join(lines)

    def extract(self, docs: List[RawDocument]) -> ExtractionResult:
        if not docs:
            return ExtractionResult(facts=[], raw_response="", used_doc_ids=[])

        self._ensure_client()
        formatted = self._format_docs(docs)
        user_msg = (
            f"Here is everything signal-worthy from today ({datetime.now().date()}):\n\n"
            f"{formatted}\n\n"
            "Return a JSON array of facts about the user. JSON only."
        )

        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=EXTRACTION_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()

        facts = self._parse_facts(text, used_doc_ids=[d.doc_id for d in docs if d.doc_id])
        return ExtractionResult(
            facts=facts,
            raw_response=text,
            used_doc_ids=[d.doc_id for d in docs if d.doc_id],
        )

    @staticmethod
    def _parse_facts(text: str, used_doc_ids: List[str]) -> List[Fact]:
        """Parse Claude's JSON response into Fact objects.

        Tolerant of code fences and stray prose around the JSON array.
        """
        text = text.strip()
        # Strip ```json fences if present.
        if text.startswith("```"):
            text = text.split("```", 2)[1] if "```" in text[3:] else text[3:]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip("` \n")
        # Find the array.
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            logger.warning("FactExtractor: no JSON array found in response: %r", text[:200])
            return []
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            logger.warning("FactExtractor: JSON parse failed (%s) for %r", e, text[start : end + 1][:200])
            return []

        facts: List[Fact] = []
        for item in payload:
            if not isinstance(item, dict) or "text" not in item:
                continue
            facts.append(
                Fact(
                    text=str(item["text"]).strip(),
                    kind=str(item.get("kind", "fact")).strip().lower(),
                    confidence=float(item.get("confidence", 0.7)),
                    source_refs=list(used_doc_ids),
                )
            )
        return facts
