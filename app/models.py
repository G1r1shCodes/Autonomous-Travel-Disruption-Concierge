from pydantic import BaseModel
from typing import Optional, Literal


class Disruption(BaseModel):
    disruption_id: str
    pnr: str
    original_flight: str
    reason: str  # "cancelled" | "missed_connection" | "delayed"


class RebookingProposal(BaseModel):
    disruption_id: str
    candidate_flight: str
    fare_delta_usd: float
    cabin_class_same: bool


class PolicyVerdict(BaseModel):
    verdict: Literal["auto_approve", "escalate", "blocked"]
    policy_rule_id: str


class PaymentResult(BaseModel):
    status: Literal["auto_approved", "passkey_required", "declined", "error"]
    token: Optional[str] = None
    merchant: str
    amount_usd: float
