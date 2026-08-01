"""Shared data shapes for the Travel-Disruption Concierge pipeline."""

from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


# ── Flight & Disruption ──────────────────────────────────────────────

class FlightSegment(BaseModel):
    """A single leg of an itinerary."""
    flight_number: str
    departure_airport: str
    arrival_airport: str
    scheduled_departure: str       # ISO 8601
    scheduled_arrival: str         # ISO 8601
    actual_departure: Optional[str] = None
    actual_arrival: Optional[str] = None
    status: Literal["on_time", "delayed", "cancelled", "diverted"] = "on_time"
    delay_minutes: int = 0


class Disruption(BaseModel):
    disruption_id: str
    pnr: str
    original_flight: str
    reason: Literal["cancelled", "missed_connection", "delayed"]
    detected_at: Optional[str] = None                # ISO 8601 timestamp
    segments: list[FlightSegment] = []               # affected segments
    connection_buffer_minutes: Optional[int] = None   # time between segments
    mct_minutes: Optional[int] = None                 # Minimum Connection Time at hub


# ── Member ────────────────────────────────────────────────────────────

class MemberProfile(BaseModel):
    """Card-member context used by Reasoning and Benefits agents."""
    member_id: str = "mbr_demo_001"
    email: str = "traveler@example.com"
    card_tier: Literal["standard", "gold", "platinum", "infinite"] = "platinum"
    loyalty_status: Literal["basic", "silver", "gold", "elite"] = "gold"
    preferences: dict = {}  # e.g. {"prefer_direct": True, "window_seat": True}


# ── Rebooking ─────────────────────────────────────────────────────────

class RebookingCandidate(BaseModel):
    """A single alternative flight option scored by the Reasoning Agent."""
    flight: str
    airline: str = "AA"
    fare_delta_usd: float
    cabin_class_same: bool = True
    departure_time: str = ""
    arrival_time: str = ""
    stops: int = 0
    arrival_delay_vs_original_min: int = 0
    score: float = 0.0               # filled by scoring algorithm
    score_breakdown: dict = {}        # per-factor contribution


class RebookingProposal(BaseModel):
    disruption_id: str
    candidate_flight: str
    fare_delta_usd: float
    cabin_class_same: bool
    all_candidates: list[RebookingCandidate] = []  # full ranked list for transparency
    reasoning_method: Literal["deterministic", "openai_ranked"] = "deterministic"
    rail_alternative: Optional[str] = None  # graceful degradation


class PolicyVerdict(BaseModel):
    verdict: Literal["auto_approve", "escalate", "blocked"]
    policy_rule_id: str


# ── Payments ──────────────────────────────────────────────────────────

class PaymentResult(BaseModel):
    status: Literal["auto_approved", "passkey_required", "declined", "error", "fallback_manual"]
    token: Optional[str] = None
    merchant: str
    amount_usd: float
    retry_count: int = 0
    fallback_url: Optional[str] = None  # manual checkout link on failure


class PravaSession(BaseModel):
    """The safe subset of a Prava session retained by this application."""
    session_id: str
    iframe_url: str
    expires_at: Optional[str] = None


# ── Benefits ──────────────────────────────────────────────────────────

class BenefitProposal(BaseModel):
    disruption_id: str
    benefit_type: Literal["trip_delay_claim", "lounge_access", "meal_comp", "hotel_comp"]
    estimated_value_usd: float
    requires_attestation: bool = False
    card_tier: str = "platinum"
    delay_duration_hours: float = 0.0
    policy_reference: str = ""


class BenefitClaim(BaseModel):
    """A fully assembled benefit claim ready for submission."""
    claim_reference: str
    benefit_type: str
    disruption_id: str
    delay_duration_hours: float
    eligible_amount_usd: float
    card_tier: str
    status: Literal["submitted", "awaiting_member_approval", "denied"] = "submitted"
    policy_reference: str = ""


# ── Comms ─────────────────────────────────────────────────────────────

class CommsNotification(BaseModel):
    """A multi-channel notification message."""
    channel: Literal["dashboard", "whatsapp", "sms", "email"]
    recipient: str = ""
    subject: str = ""
    body: str = ""
    before_itinerary: dict = {}    # original flight details
    after_itinerary: dict = {}     # new flight details
    actions: list[dict] = []       # e.g. [{"label": "Approve", "url": "..."}]


# ── Member Decision ──────────────────────────────────────────────────

class MemberDecision(BaseModel):
    decision: Literal["approve", "decline"]
