"""Recall tool — agent queries the semantic fact store.

This is the tool that closes the loop on Summer's "context engine" pitch.
The background engine ingests signals and stores facts; here the agent asks
the store, in natural language, for facts relevant to whatever situation
just came up.

Provide a FactStore at construction time. If you don't have one, don't
register this provider.
"""

from typing import Any, Dict, List, Optional, Tuple

from ..tool_system import (
    BaseToolSetProvider,
    Parameter,
    ParameterType,
    Tool,
)


class RecallToolProvider(BaseToolSetProvider):
    """Exposes a semantic search over the user's fact store."""

    def __init__(self, fact_store, websocket_handler=None):
        super().__init__(websocket_handler)
        self.fact_store = fact_store

    def init(self) -> Tuple[List[Tool], Dict[str, Any], Dict[str, Dict[str, Any]]]:
        tools = [
            Tool(
                id="recall_relevant_facts",
                name="recall_relevant_facts",
                display_name="Recall Relevant Facts",
                description=(
                    "Search your semantic memory of the user for facts relevant to a query. "
                    "Use this whenever the conversation surfaces a situation you might "
                    "have prior context on: a time of day, a place, a habit, a person, a "
                    "task, a preference, a recurring email/order/meeting. The background "
                    "context engine has been quietly building this index from the user's "
                    "conversations, calendar, and emails.\n\n"
                    "Pass a natural-language `query` describing the situation. You'll get "
                    "back up to `top_k` facts ranked by semantic similarity, each with a "
                    "score, a kind (fact | pattern | preference), and a confidence."
                ),
                parameters={
                    "query": Parameter(
                        name="query",
                        type=ParameterType.STRING,
                        description=(
                            "Natural-language description of the situation you want context for. "
                            "Examples: 'late-night deep work session in the library', "
                            "'how the user likes to be addressed', "
                            "'what the user usually orders for coffee'."
                        ),
                        required=True,
                    ),
                    "top_k": Parameter(
                        name="top_k",
                        type=ParameterType.INTEGER,
                        description="Max number of facts to return. Default 5, range 1–20.",
                        required=False,
                        default=5,
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
        if tool_id != "recall_relevant_facts":
            return None, f"Unknown tool: {tool_id}"

        query = (tool_parameters.get("query") or "").strip()
        if not query:
            return None, "query cannot be empty"
        top_k = int(tool_parameters.get("top_k") or 5)
        top_k = max(1, min(20, top_k))

        results = self.fact_store.search(query, top_k=top_k)
        if not results:
            return {"matches": [], "message": "No facts in memory match that query."}, None

        return {
            "matches": [
                {
                    "text": f.text,
                    "kind": f.kind,
                    "confidence": round(f.confidence, 3),
                    "score": round(f.score or 0.0, 3),
                    "source_refs": f.source_refs,
                }
                for f in results
            ]
        }, None
