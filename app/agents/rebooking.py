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

        if verdict.verdict == "escalate":
            log_event("rebooking_agent", "gate", "awaiting_member_approval", proposal.model_dump())
            return {"status": "awaiting_member_approval", "reason": verdict.policy_rule_id}

        # The browser dashboard starts the real Prava passkey flow. We retain
        # this method only for the command-line scaffold.
        return {"status": "requires_prava_dashboard", "flight": proposal.candidate_flight}
