import yaml
from pathlib import Path
from app.models import RebookingProposal, PolicyVerdict
from app.audit import log_event

POLICY_PATH = Path(__file__).parent.parent / "policy" / "policy.yaml"


class Orchestrator:
    """Single choke point: every agent proposes, only this class decides."""

    def __init__(self):
        self.policy = yaml.safe_load(POLICY_PATH.read_text())

    def gate(self, proposal: RebookingProposal) -> PolicyVerdict:
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

        log_event(
            agent="orchestrator",
            sub_component="policy_gate",
            action="evaluate_proposal",
            detail=proposal.model_dump(),
            policy_verdict=verdict.verdict,
        )
        return verdict
