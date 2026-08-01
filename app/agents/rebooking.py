from app.models import RebookingProposal, PolicyVerdict
from app.integrations.prava_client import PravaClient
from app.audit import log_event


class RebookingAgent:
    def __init__(self):
        self.prava = PravaClient()

    def execute(self, proposal: RebookingProposal, verdict: PolicyVerdict):
        if verdict.verdict == "blocked":
            log_event("rebooking_agent", "gate", "blocked_by_policy", proposal.model_dump())
            return {"status": "blocked", "reason": verdict.policy_rule_id}

        payment = self.prava.request_payment_token(
            merchant=f"airline:{proposal.candidate_flight[:2]}",
            amount_usd=proposal.fare_delta_usd,
        )

        if payment.status == "auto_approved":
            # Mock Amadeus booking call -- swap for real Flight Create Orders
            log_event("rebooking_agent", "amadeus", "book_flight",
                       {"flight": proposal.candidate_flight, "token": payment.token})
            return {"status": "booked", "flight": proposal.candidate_flight, "token": payment.token}

        if payment.status == "passkey_required":
            return {"status": "awaiting_member_passkey_approval", "flight": proposal.candidate_flight}

        return {"status": "payment_failed"}
