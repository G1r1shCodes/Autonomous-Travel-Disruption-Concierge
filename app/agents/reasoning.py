"""
Reasoning Agent -- scoring & candidate selection.
Mocked candidate list for the demo; swap `candidates` for a real
Amadeus Flight Offers Search call when you have time.
"""
from app.models import Disruption, RebookingProposal
from app.audit import log_event


class ReasoningAgent:
    def propose(self, disruption: Disruption) -> RebookingProposal:
        candidates = [
            {"flight": "AA318", "fare_delta_usd": 42, "cabin_class_same": True},
            {"flight": "DL551", "fare_delta_usd": 120, "cabin_class_same": True},
        ]
        best = min(candidates, key=lambda c: c["fare_delta_usd"])

        proposal = RebookingProposal(
            disruption_id=disruption.disruption_id,
            candidate_flight=best["flight"],
            fare_delta_usd=best["fare_delta_usd"],
            cabin_class_same=best["cabin_class_same"],
        )
        log_event(
            agent="reasoning_agent",
            sub_component="scorer",
            action="propose_alternative",
            detail=proposal.model_dump(),
        )
        return proposal
