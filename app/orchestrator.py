"""Orchestrator — single choke point: every agent proposes, only this class decides.

Matches §3.2 of the pitch doc:
- Single reusable policy gate for Rebooking and Benefits proposals
- YAML-driven thresholds for fare delta, arrival delay, benefits auto-filing
- Per-agent-attributed audit logging on every gate decision
"""
import yaml
from pathlib import Path
from app.models import BenefitProposal, RebookingProposal, PolicyVerdict
from app.audit import log_event

POLICY_PATH = Path(__file__).parent.parent / "policy" / "policy.yaml"


class Orchestrator:
    """Single choke point: every agent proposes, only this class decides."""

    def __init__(self):
        self.policy = yaml.safe_load(POLICY_PATH.read_text())

    def gate(self, proposal: RebookingProposal) -> PolicyVerdict:
        """Evaluate a rebooking proposal against the YAML policy engine.

        Decision tree:
        1. Cabin downgrade forbidden → blocked
        2. Fare delta ≤ auto_approve_under_usd → auto_approve
        3. Fare delta ≤ escalate_under_usd → escalate (member review)
        4. Fare delta > escalate_under_usd → blocked (human agent handoff)
        """
        rules = self.policy["fare_delta"]
        delta = proposal.fare_delta_usd

        if not proposal.cabin_class_same and not self.policy["cabin_class"]["allow_downgrade"]:
            verdict = PolicyVerdict(verdict="blocked", policy_rule_id="cabin-downgrade-forbidden")
        elif delta <= rules["auto_approve_under_usd"]:
            verdict = PolicyVerdict(verdict="auto_approve", policy_rule_id="RB-003-fare-delta-under-50")
        elif delta <= rules["escalate_under_usd"]:
            verdict = PolicyVerdict(verdict="escalate", policy_rule_id="RB-004-fare-delta-under-150")
        else:
            verdict = PolicyVerdict(verdict="blocked", policy_rule_id="RB-005-fare-delta-over-cap")

        # Serialize candidates for audit logging (they may be Pydantic objects)
        candidates_for_log = []
        for c in (proposal.all_candidates or [])[:3]:
            candidates_for_log.append(c if isinstance(c, dict) else (c.model_dump() if hasattr(c, 'model_dump') else c))

        log_event(
            agent="orchestrator",
            sub_component="policy_gate",
            action="evaluate_proposal",
            detail={
                "disruption_id": proposal.disruption_id,
                "candidate_flight": proposal.candidate_flight,
                "fare_delta_usd": proposal.fare_delta_usd,
                "cabin_class_same": proposal.cabin_class_same,
                "reasoning_method": proposal.reasoning_method,
                "top_candidates": candidates_for_log,
            },
            policy_verdict=verdict.verdict,
            disruption_id=proposal.disruption_id,
        )
        return verdict

    def gate_benefit(self, proposal: BenefitProposal) -> PolicyVerdict:
        """Apply the same central trust boundary to benefit actions.

        Uses the benefits section of policy.yaml for auto-filing thresholds.
        """
        benefits_policy = self.policy.get("benefits", {})
        attestation_threshold = benefits_policy.get("attestation_required_above_usd", 500)

        if proposal.requires_attestation or proposal.estimated_value_usd > attestation_threshold:
            verdict = PolicyVerdict(
                verdict="escalate",
                policy_rule_id=f"BN-002-attestation-required-above-{attestation_threshold}",
            )
        else:
            verdict = PolicyVerdict(
                verdict="auto_approve",
                policy_rule_id="BN-001-confirmed-disruption-benefit",
            )

        log_event(
            agent="orchestrator",
            sub_component="policy_gate",
            action="evaluate_benefit_proposal",
            detail=proposal.model_dump(),
            policy_verdict=verdict.verdict,
            disruption_id=proposal.disruption_id,
        )
        return verdict
