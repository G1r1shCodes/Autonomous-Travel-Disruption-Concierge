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


class PravaSession(BaseModel):
    """The safe subset of a Prava session retained by this application."""

    session_id: str
    iframe_url: str
    expires_at: Optional[str] = None


class BenefitProposal(BaseModel):
    disruption_id: str
    benefit_type: Literal["trip_delay_claim", "lounge_access"]
    estimated_value_usd: float
    requires_attestation: bool = False
