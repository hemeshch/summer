"""Stub DoorDash tool.

DoorDash has no public API for placing orders. A real integration would
require either a partner agreement or browser/mobile-API automation against
the user's account — both well beyond the scope of this demo. For now this
tool pretends to place the order: it logs the intent, returns a plausible
order confirmation, and writes a fact to the semantic memory so the agent
remembers what was ordered (closing the demo's working-memory loop).

When (and if) real DoorDash integration ships, the call_tool body is the
only thing that changes — the tool schema, the memory write, and the agent
prompting stay the same.
"""

import random
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..tool_system import (
    BaseToolSetProvider,
    Parameter,
    ParameterType,
    Tool,
)


def _fake_order_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"DD-{suffix}"


class DoorDashToolProvider(BaseToolSetProvider):
    """Exposes place_doordash_order. Optional fact_store auto-writes a
    'user ordered X' fact on success so the working memory updates instantly.
    """

    def __init__(self, fact_store=None, websocket_handler=None):
        super().__init__(websocket_handler)
        self.fact_store = fact_store

    def init(self) -> Tuple[List[Tool], Dict[str, Any], Dict[str, Dict[str, Any]]]:
        tools = [
            Tool(
                id="place_doordash_order",
                name="place_doordash_order",
                display_name="Place DoorDash Order",
                description=(
                    "Place a DoorDash order on the user's behalf. ONLY call this after "
                    "the user has explicitly confirmed they want the order — never on "
                    "your own initiative without a 'yes' or equivalent.\n\n"
                    "The tool returns an order_id, an ETA, and a total. After it succeeds, "
                    "report the result back to the user briefly (e.g., 'placed — ETA 15 min, "
                    "$7.40').\n\n"
                    "Note: this is currently a stub. It records intent and updates memory; it "
                    "does not yet contact DoorDash. Treat its success response as a successful "
                    "real order for demo purposes."
                ),
                parameters={
                    "item": Parameter(
                        name="item",
                        type=ParameterType.STRING,
                        description="What to order, e.g., 'iced matcha latte, oat milk'.",
                        required=True,
                    ),
                    "restaurant": Parameter(
                        name="restaurant",
                        type=ParameterType.STRING,
                        description="The vendor, e.g., 'Agora Coffee'.",
                        required=True,
                    ),
                    "delivery_address": Parameter(
                        name="delivery_address",
                        type=ParameterType.STRING,
                        description=(
                            "Optional delivery address override. If omitted, the user's "
                            "default address is assumed."
                        ),
                        required=False,
                    ),
                    "tip_dollars": Parameter(
                        name="tip_dollars",
                        type=ParameterType.NUMBER,
                        description="Tip in USD. Defaults to $3.00 when omitted.",
                        required=False,
                        default=3.0,
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
        if tool_id != "place_doordash_order":
            return None, f"Unknown tool: {tool_id}"

        item = (tool_parameters.get("item") or "").strip()
        restaurant = (tool_parameters.get("restaurant") or "").strip()
        if not item or not restaurant:
            return None, "item and restaurant are both required"

        address = (tool_parameters.get("delivery_address") or "").strip() or "default address on file"
        try:
            tip = float(tool_parameters.get("tip_dollars") or 3.0)
        except (TypeError, ValueError):
            tip = 3.0

        order_id = _fake_order_id()
        # Hand-wave a price — for demo purposes only.
        subtotal = round(random.uniform(5.5, 9.5), 2)
        fees = round(subtotal * 0.18 + 1.99, 2)
        total = round(subtotal + fees + tip, 2)
        eta_minutes = random.randint(12, 22)
        placed_at = datetime.now(timezone.utc).isoformat()
        local_time = datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip()

        print(
            f"[DoorDashTool] (STUB) order {order_id}: {item!r} from {restaurant!r} "
            f"→ {address}; subtotal ${subtotal:.2f}, fees ${fees:.2f}, tip ${tip:.2f}, "
            f"total ${total:.2f}, ETA {eta_minutes} min"
        )

        # Reinforce semantic memory so future late-night queries surface this.
        memory_note = None
        if self.fact_store is not None:
            try:
                from io_system.context_engine.fact_store import Fact
                conversation_id = per_conversation_state.get("_conversation_id", "default")
                fact_text = (
                    f"On {local_time}, the user placed a DoorDash order for "
                    f"'{item}' from {restaurant} (total ${total:.2f})."
                )
                stored = self.fact_store.add(
                    Fact(
                        text=fact_text,
                        kind="fact",
                        confidence=0.95,
                        source_refs=[f"tool:doordash:{order_id}"],
                        metadata={
                            "order_id": order_id,
                            "item": item,
                            "restaurant": restaurant,
                            "total": total,
                            "conversation_id": conversation_id,
                        },
                    )
                )
                memory_note = f"memory updated (fact #{stored.id})"
            except Exception as e:
                memory_note = f"memory update failed: {e}"

        return {
            "status": "placed",
            "order_id": order_id,
            "item": item,
            "restaurant": restaurant,
            "delivery_address": address,
            "subtotal": subtotal,
            "fees": fees,
            "tip": tip,
            "total": total,
            "eta_minutes": eta_minutes,
            "placed_at_utc": placed_at,
            "memory_note": memory_note,
            "_stub": True,  # honest signal the agent can ignore in messaging
        }, None
