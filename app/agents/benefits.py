"""Benefits Agent — identifies and auto-files card-member benefits after a disruption.

Matches §3.5 of the pitch doc:
- Trip-delay auto-filing with delay duration, policy reference, claim assembly
- Lounge access voucher issuance for extended waits
- Loyalty-aware compensation (meal/hotel comp weighted by card tier)
- Multiple benefit proposals per disruption
"""
import yaml
from pathlib import Path

from app.audit import log_event
from app.models import BenefitProposal, BenefitClaim, Disruption, MemberProfile, PolicyVerdict

POLICY_PATH = Path(__file__).parent.parent.parent / "policy" / "policy.yaml"


# ── Benefit value tables by card tier ────────────────────────────────

TRIP_DELAY_VALUES = {
    "standard": 100.0,
    "gold": 200.0,
    "platinum": 500.0,
    "infinite": 1000.0,
}

LOUNGE_VALUES = {
    "standard": 0.0,       # not eligible
    "gold": 35.0,
    "platinum": 50.0,
    "infinite": 75.0,
}

MEAL_COMP_VALUES = {
    "standard": 15.0,
    "gold": 25.0,
    "platinum": 40.0,
    "infinite": 60.0,
}

HOTEL_COMP_VALUES = {
    "standard": 100.0,
    "gold": 150.0,
    "platinum": 250.0,
    "infinite": 350.0,
}


class BenefitsAgent:
    """Identifies eligible benefits and assembles claims for auto-filing."""

    def __init__(self):
        self.policy = yaml.safe_load(POLICY_PATH.read_text())
        self.benefits_policy = self.policy.get("benefits", {})

    def _estimate_delay_hours(self, disruption: Disruption) -> float:
        """Estimate the delay duration from disruption data."""
        if disruption.reason == "cancelled":
            return 4.0  # assume minimum 4-hour disruption for cancellations
        if disruption.segments:
            max_delay = max(s.delay_minutes for s in disruption.segments)
            return max_delay / 60.0
        return 3.0  # default

    def propose_all(
        self, disruption: Disruption, member: MemberProfile = None
    ) -> list[BenefitProposal]:
        """Generate all eligible benefit proposals for a disruption.

        Returns multiple proposals (trip delay, lounge, meal, hotel) based
        on the disruption type, delay duration, and card tier.
        """
        if member is None:
            member = MemberProfile()

        delay_hours = self._estimate_delay_hours(disruption)
        card_tier = member.card_tier
        proposals = []

        # ── Trip-delay auto-filing (§3.5) ────────────────────────────
        auto_file_threshold = self.benefits_policy.get("trip_delay_auto_file_after_hours", 3)
        if delay_hours >= auto_file_threshold:
            value = TRIP_DELAY_VALUES.get(card_tier, 100.0)
            attestation_threshold = self.benefits_policy.get("attestation_required_above_usd", 500)
            proposals.append(BenefitProposal(
                disruption_id=disruption.disruption_id,
                benefit_type="trip_delay_claim",
                estimated_value_usd=value,
                requires_attestation=value > attestation_threshold,
                card_tier=card_tier,
                delay_duration_hours=delay_hours,
                policy_reference=f"BN-TD-{card_tier}-{auto_file_threshold}hr",
            ))

        # ── Lounge access voucher (§3.5) ─────────────────────────────
        lounge_threshold = self.benefits_policy.get("lounge_auto_issue_after_hours", 2)
        lounge_value = LOUNGE_VALUES.get(card_tier, 0.0)
        if delay_hours >= lounge_threshold and lounge_value > 0:
            proposals.append(BenefitProposal(
                disruption_id=disruption.disruption_id,
                benefit_type="lounge_access",
                estimated_value_usd=lounge_value,
                requires_attestation=False,
                card_tier=card_tier,
                delay_duration_hours=delay_hours,
                policy_reference=f"BN-LA-{card_tier}-{lounge_threshold}hr",
            ))

        # ── Meal compensation ────────────────────────────────────────
        if delay_hours >= 2.0:
            meal_value = MEAL_COMP_VALUES.get(card_tier, 15.0)
            meal_cap = self.benefits_policy.get("meal_comp_auto_approve_usd", 50)
            proposals.append(BenefitProposal(
                disruption_id=disruption.disruption_id,
                benefit_type="meal_comp",
                estimated_value_usd=meal_value,
                requires_attestation=meal_value > meal_cap,
                card_tier=card_tier,
                delay_duration_hours=delay_hours,
                policy_reference=f"BN-MC-{card_tier}",
            ))

        # ── Hotel compensation (overnight disruptions) ───────────────
        if delay_hours >= 8.0 or disruption.reason == "cancelled":
            hotel_value = HOTEL_COMP_VALUES.get(card_tier, 100.0)
            hotel_cap = self.benefits_policy.get("hotel_comp_auto_approve_usd", 250)
            proposals.append(BenefitProposal(
                disruption_id=disruption.disruption_id,
                benefit_type="hotel_comp",
                estimated_value_usd=hotel_value,
                requires_attestation=hotel_value > hotel_cap,
                card_tier=card_tier,
                delay_duration_hours=delay_hours,
                policy_reference=f"BN-HC-{card_tier}",
            ))

        log_event(
            agent="benefits_agent",
            sub_component="benefit_matcher",
            action="propose_benefits",
            detail={
                "disruption_id": disruption.disruption_id,
                "delay_hours": delay_hours,
                "card_tier": card_tier,
                "proposals_count": len(proposals),
                "benefit_types": [p.benefit_type for p in proposals],
            },
            disruption_id=disruption.disruption_id,
        )
        return proposals

    def propose(self, disruption: Disruption) -> BenefitProposal:
        """Backward-compatible: return the highest-value single proposal."""
        all_proposals = self.propose_all(disruption)
        if not all_proposals:
            return BenefitProposal(
                disruption_id=disruption.disruption_id,
                benefit_type="trip_delay_claim",
                estimated_value_usd=0.0,
                requires_attestation=False,
            )
        return max(all_proposals, key=lambda p: p.estimated_value_usd)

    def execute(self, proposal: BenefitProposal, verdict: PolicyVerdict) -> dict:
        """File or escalate a single benefit claim."""
        if verdict.verdict != "auto_approve":
            log_event(
                agent="benefits_agent",
                sub_component="claim_submission",
                action="awaiting_member_approval",
                detail=proposal.model_dump(),
                policy_verdict=verdict.verdict,
                disruption_id=proposal.disruption_id,
            )
            return {"status": "awaiting_member_approval", "reason": verdict.policy_rule_id}

        claim = BenefitClaim(
            claim_reference=f"claim_{proposal.disruption_id[-4:]}_{proposal.benefit_type[:2]}",
            benefit_type=proposal.benefit_type,
            disruption_id=proposal.disruption_id,
            delay_duration_hours=proposal.delay_duration_hours,
            eligible_amount_usd=proposal.estimated_value_usd,
            card_tier=proposal.card_tier,
            status="submitted",
            policy_reference=proposal.policy_reference,
        )

        log_event(
            agent="benefits_agent",
            sub_component="claim_submission",
            action="submit_claim",
            detail=claim.model_dump(),
            policy_verdict=verdict.verdict,
            disruption_id=proposal.disruption_id,
        )
        return claim.model_dump()

    def execute_all(self, proposals: list[BenefitProposal], orchestrator) -> list[dict]:
        """File all eligible benefit claims through the orchestrator gate."""
        results = []
        for proposal in proposals:
            verdict = orchestrator.gate_benefit(proposal)
            result = self.execute(proposal, verdict)
            results.append({
                "proposal": proposal.model_dump(),
                "verdict": verdict.model_dump(),
                "result": result,
            })
        return results
