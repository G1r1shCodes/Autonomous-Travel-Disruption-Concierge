"""
Monitor Agent -- detection.
Swap `detect` with real Amadeus Flight Status polling when ready.
Keeping it mocked now so the rest of the crew is demoable immediately.
"""
from app.models import Disruption
from app.audit import log_event


class MonitorAgent:
    def detect(self, pnr: str) -> Disruption:
        disruption = Disruption(
            disruption_id="dis_demo_001",
            pnr=pnr,
            original_flight="AA202",
            reason="cancelled",
        )
        log_event(
            agent="monitor_agent",
            sub_component="amadeus_poll",
            action="detect_disruption",
            detail=disruption.model_dump(),
        )
        return disruption
