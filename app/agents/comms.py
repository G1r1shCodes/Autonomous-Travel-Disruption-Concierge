"""Comms Agent -- records the member-facing update for the MVP."""
from app.audit import log_event
from app.models import Disruption


class CommsAgent:
    def notify(self, disruption: Disruption, rebooking: dict, benefit: dict) -> dict:
        message = (
            f"Disruption {disruption.original_flight}: rebooking status is {rebooking['status']}; "
            f"benefit status is {benefit['status']}."
        )
        log_event(
            agent="comms_agent",
            sub_component="member_notification",
            action="queue_notification",
            detail={"channel": "dashboard", "message": message},
        )
        return {"status": "queued", "channel": "dashboard", "message": message}
