"""Proactive check-in tool — the agent schedules a future wake-up of itself.

When the model calls ``schedule_proactive_check_in(delay_minutes, context)``,
we persist a row in the ProactiveScheduler's sqlite store. The scheduler's
background thread fires the row when due, which then runs Claude with the
saved context as a fresh prompt and routes the response to the configured
output handler (e.g., iMessage).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..tool_system import (
    BaseToolSetProvider,
    Parameter,
    ParameterType,
    Tool,
)


class ProactiveSchedulerToolProvider(BaseToolSetProvider):
    """Exposes proactive scheduling tools.

    Construct with the ProactiveScheduler instance the rest of the app uses
    so the tool persists into the same store the polling loop watches.
    """

    def __init__(self, scheduler, websocket_handler=None):
        super().__init__(websocket_handler)
        self.scheduler = scheduler

    def init(self) -> Tuple[List[Tool], Dict[str, Any], Dict[str, Dict[str, Any]]]:
        tools = [
            Tool(
                id="schedule_proactive_check_in",
                name="schedule_proactive_check_in",
                display_name="Schedule Proactive Check-In",
                description=(
                    "Schedule a future moment to message the user, unprompted.\n\n"
                    "Use this when the conversation surfaces something worth following up on later:\n"
                    "- The user mentions an upcoming deadline, exam, flight, or meeting.\n"
                    "- The user shares a goal or task and would benefit from a nudge.\n"
                    "- A pattern emerges (e.g., late-night work sessions) where a check-in adds value.\n\n"
                    "The `context` you pass is what YOU will receive when the check-in fires. "
                    "Write it as a self-contained note to your future self: include the user's "
                    "situation, what to ask or say, and the desired tone. When the check-in fires "
                    "you can choose not to send anything by responding with `SKIP`."
                ),
                parameters={
                    "delay_minutes": Parameter(
                        name="delay_minutes",
                        type=ParameterType.NUMBER,
                        description=(
                            "How many minutes from now to fire the check-in. "
                            "Examples: 30 (in half an hour), 240 (in 4 hours), "
                            "720 (in 12 hours)."
                        ),
                        required=True,
                    ),
                    "context": Parameter(
                        name="context",
                        type=ParameterType.STRING,
                        description=(
                            "A note to your future self explaining what this check-in is about. "
                            "Will be passed back as the prompt when the check-in fires."
                        ),
                        required=True,
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
        if tool_id != "schedule_proactive_check_in":
            return None, f"Unknown tool: {tool_id}"

        delay_minutes = tool_parameters.get("delay_minutes")
        context = (tool_parameters.get("context") or "").strip()

        if delay_minutes is None or delay_minutes <= 0:
            return None, "delay_minutes must be a positive number"
        if not context:
            return None, "context cannot be empty"

        conversation_id = per_conversation_state.get("_conversation_id", "default")
        fire_at = datetime.now(timezone.utc) + timedelta(minutes=float(delay_minutes))

        check_in_id = self.scheduler.schedule(
            conversation_id=conversation_id,
            fire_at=fire_at,
            context=context,
        )

        return {
            "check_in_id": check_in_id,
            "fire_at_utc": fire_at.isoformat(),
            "message": (
                f"Scheduled check-in #{check_in_id} for "
                f"{fire_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')}."
            ),
        }, None
