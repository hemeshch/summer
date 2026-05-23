"""Direct-write tool into the semantic fact store.

Pairs with recall_relevant_facts. Where recall is the read side, this is the
write side: the agent calls it the moment it learns something worth
remembering (e.g., user confirmed they want a matcha at 2am — record that
the pattern is reinforced).

This bypasses the nightly extractor loop so confirmations land in memory
instantly, not after the next 3am ingest.
"""

from typing import Any, Dict, List, Optional, Tuple

from ..tool_system import (
    BaseToolSetProvider,
    Parameter,
    ParameterType,
    Tool,
)


VALID_KINDS = {"fact", "pattern", "preference"}


class MemoryWriteToolProvider(BaseToolSetProvider):
    """Exposes a direct add_fact_to_memory tool over a FactStore."""

    def __init__(self, fact_store, websocket_handler=None):
        super().__init__(websocket_handler)
        self.fact_store = fact_store

    def init(self) -> Tuple[List[Tool], Dict[str, Any], Dict[str, Dict[str, Any]]]:
        tools = [
            Tool(
                id="add_fact_to_memory",
                name="add_fact_to_memory",
                display_name="Add Fact to Memory",
                description=(
                    "Write a fact about the user directly into your semantic memory. "
                    "Use this the moment you learn something worth remembering long-term:\n"
                    "- The user confirms a habit you suspected (write it as a `pattern`).\n"
                    "- The user states a preference (write it as a `preference`).\n"
                    "- A concrete event happened that you'll need to recall later (write it as a `fact`).\n\n"
                    "Examples of GOOD facts:\n"
                    "- 'User confirmed they want a matcha latte from Agora at 2am during library sessions.'\n"
                    "- 'User placed a DoorDash order for matcha latte from Agora Coffee on 2026-05-23 at 02:14am, total $7.40.'\n"
                    "- 'User dislikes loud notifications between 8am and 10am.'\n\n"
                    "Don't use this for trivia or ephemeral state. The store deduplicates and "
                    "merges confidence, so re-writing a known pattern reinforces it rather "
                    "than creating a duplicate."
                ),
                parameters={
                    "text": Parameter(
                        name="text",
                        type=ParameterType.STRING,
                        description=(
                            "Self-contained sentence about the user, in third person. "
                            "Be concrete (specific places, items, times) rather than vague."
                        ),
                        required=True,
                    ),
                    "kind": Parameter(
                        name="kind",
                        type=ParameterType.STRING,
                        description=(
                            "One of: 'fact' (concrete event/attribute), "
                            "'pattern' (recurring behavior), "
                            "'preference' (taste/style/tone). "
                            "Defaults to 'fact'."
                        ),
                        required=False,
                        default="fact",
                    ),
                    "confidence": Parameter(
                        name="confidence",
                        type=ParameterType.NUMBER,
                        description=(
                            "How confident you are, 0.5–1.0. Explicit user confirmation: ~0.9. "
                            "Strong inference from current conversation: ~0.7. Defaults to 0.8."
                        ),
                        required=False,
                        default=0.8,
                    ),
                },
            )
        ]
        return tools, {}, {}

    def call_tool(
        self,
        tool_id: str,
        tool_parameters: Dict[str, Any],
        per_conversation_state: Dict[str, Any],
        global_state: Dict[str, Any],
    ) -> Tuple[Any, Optional[str]]:
        if tool_id != "add_fact_to_memory":
            return None, f"Unknown tool: {tool_id}"

        # Lazy import so this module stays importable on systems without the
        # context_engine deps (sentence-transformers, etc.).
        from io_system.context_engine.fact_store import Fact

        text = (tool_parameters.get("text") or "").strip()
        if not text:
            return None, "text cannot be empty"

        kind = str(tool_parameters.get("kind") or "fact").strip().lower()
        if kind not in VALID_KINDS:
            return None, f"kind must be one of {sorted(VALID_KINDS)}, got {kind!r}"

        try:
            confidence = float(tool_parameters.get("confidence") or 0.8)
        except (TypeError, ValueError):
            return None, "confidence must be a number"
        confidence = max(0.5, min(1.0, confidence))

        conversation_id = per_conversation_state.get("_conversation_id", "default")
        source_ref = f"tool:add_fact:{conversation_id}"

        # Insert. FactStore dedupes by cosine similarity and merges confidence
        # for near-duplicates rather than inserting twice.
        before = self.fact_store.count()
        stored = self.fact_store.add(
            Fact(
                text=text,
                kind=kind,
                confidence=confidence,
                source_refs=[source_ref],
            )
        )
        after = self.fact_store.count()
        was_merged = (after == before)

        return {
            "fact_id": stored.id,
            "stored_text": stored.text,
            "kind": stored.kind,
            "merged_into_existing": was_merged,
            "store_size": after,
            "message": (
                f"Reinforced existing memory #{stored.id}."
                if was_merged
                else f"New memory #{stored.id} stored."
            ),
        }, None
