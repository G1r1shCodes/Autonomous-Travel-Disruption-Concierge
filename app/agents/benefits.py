"""Benefits Agent -- identifies card-member benefits after a disruption."""
from app.audit import log_event
from app.models import BenefitProposal, Disruption, PolicyVerdict


class BenefitsAgent:
    def propose(self, disruption: Disruption) -> BenefitProposal:
        # The external card-benefits API is intentionally mocked for the MVP.
        proposal = BenefitProposal(
            disruption_id=disruption.disruption_id,
            benefit_type="trip_delay_claim",
            estimated_value_usd=125.0,
            requires_attestation=False,
        )
        log_event(
            agent="benefits_agent",
            sub_component="benefit_matcher",
            action="propose_benefit",
            detail=proposal.model_dump(),
        )
        return proposal

    def execute(self, proposal: BenefitProposal, verdict: PolicyVerdict) -> dict:
        if verdict.verdict != "auto_approve":
            log_event(
                agent="benefits_agent",
                sub_component="claim_submission",
                action="awaiting_member_approval",
                detail=proposal.model_dump(),
                policy_verdict=verdict.verdict,
            )
            return {"status": "awaiting_member_approval", "reason": verdict.policy_rule_id}

        claim_reference = f"claim_{proposal.disruption_id[-4:]}"
        log_event(
            agent="benefits_agent",
            sub_component="claim_submission",
            action="submit_claim",
            detail={"benefit_type": proposal.benefit_type, "claim_reference": claim_reference},
            policy_verdict=verdict.verdict,
        )
        return {"status": "submitted", "claim_reference": claim_reference}
