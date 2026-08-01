"""Reasoning Agent — 6-factor weighted scoring with optional OpenAI ranking.

Matches §4.2 of the pitch doc:
- Weighted scoring: price delta, cabin class, arrival delay, stops,
  departure time preference, and loyalty bonus
- Multiple realistic candidates (5 alternatives)
- Rail alternative suggestion when no same-day flight exists (§3.3)
- OpenAI ranking as optional enhancement on top of deterministic scoring
"""
import json
import os
import yaml
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel
from app.models import Disruption, RebookingProposal, RebookingCandidate
from app.audit import log_event

class OpenAIChoice(BaseModel):
    candidate_flight: str
    reason: str


POLICY_PATH = Path(__file__).parent.parent.parent / "policy" / "policy.yaml"


# ── Mock candidate data simulating Amadeus Flight Offers Search ──────

MOCK_CANDIDATES = {
    "cancelled": [
        RebookingCandidate(flight="AA318", airline="AA", fare_delta_usd=42, cabin_class_same=True,
                           departure_time="10:30", arrival_time="12:45", stops=0, arrival_delay_vs_original_min=30),
        RebookingCandidate(flight="DL551", airline="DL", fare_delta_usd=120, cabin_class_same=True,
                           departure_time="13:15", arrival_time="15:30", stops=0, arrival_delay_vs_original_min=195),
        RebookingCandidate(flight="UA872", airline="UA", fare_delta_usd=65, cabin_class_same=True,
                           departure_time="11:00", arrival_time="14:20", stops=1, arrival_delay_vs_original_min=95),
        RebookingCandidate(flight="AA442", airline="AA", fare_delta_usd=28, cabin_class_same=False,
                           departure_time="09:45", arrival_time="12:00", stops=0, arrival_delay_vs_original_min=15),
        RebookingCandidate(flight="B6209", airline="B6", fare_delta_usd=89, cabin_class_same=True,
                           departure_time="14:30", arrival_time="16:45", stops=0, arrival_delay_vs_original_min=270),
    ],
    "missed_connection": [
        RebookingCandidate(flight="UA790", airline="UA", fare_delta_usd=55, cabin_class_same=True,
                           departure_time="12:30", arrival_time="18:15", stops=0, arrival_delay_vs_original_min=130),
        RebookingCandidate(flight="AA115", airline="AA", fare_delta_usd=95, cabin_class_same=True,
                           departure_time="14:00", arrival_time="19:50", stops=0, arrival_delay_vs_original_min=225),
        RebookingCandidate(flight="DL302", airline="DL", fare_delta_usd=38, cabin_class_same=True,
                           departure_time="13:00", arrival_time="20:30", stops=1, arrival_delay_vs_original_min=265),
    ],
    "delayed": [
        RebookingCandidate(flight="DL1920", airline="DL", fare_delta_usd=35, cabin_class_same=True,
                           departure_time="12:00", arrival_time="19:35", stops=0, arrival_delay_vs_original_min=45),
        RebookingCandidate(flight="AA780", airline="AA", fare_delta_usd=72, cabin_class_same=True,
                           departure_time="13:30", arrival_time="20:15", stops=0, arrival_delay_vs_original_min=85),
        RebookingCandidate(flight="UA330", airline="UA", fare_delta_usd=15, cabin_class_same=False,
                           departure_time="11:45", arrival_time="19:10", stops=1, arrival_delay_vs_original_min=20),
    ],
}

# Rail alternatives for graceful degradation (§3.3)
RAIL_ALTERNATIVES = {
    "JFK-ORD": None,                # no rail option
    "BOS-NYC": "Amtrak Acela Express — 3h 30m, $89",
    "default": None,
}


class ReasoningAgent:
    """Scores and selects the best rebooking candidate using a weighted
    multi-factor algorithm, with optional OpenAI re-ranking."""

    def __init__(self):
        self.policy = yaml.safe_load(POLICY_PATH.read_text())
        self.weights = self.policy.get("scoring", {})

    # ── 6-factor weighted scoring (§4.2) ─────────────────────────────

    def _score_candidate(self, c: RebookingCandidate, is_loyalty_elite: bool = False) -> RebookingCandidate:
        """Score a single candidate across 6 factors, returning the
        candidate with score and breakdown filled in."""
        w = self.weights

        # Factor 1: Price (lower is better, normalized against $200 cap)
        price_score = max(0, 1.0 - (c.fare_delta_usd / 200.0))

        # Factor 2: Cabin class (1.0 if same, 0.0 if downgraded)
        cabin_score = 1.0 if c.cabin_class_same else 0.0

        # Factor 3: Arrival delay vs original (lower is better, normalized against 6 hrs)
        delay_score = max(0, 1.0 - (c.arrival_delay_vs_original_min / 360.0))

        # Factor 4: Stops (0 stops = 1.0, 1 stop = 0.5, 2+ = 0.0)
        stops_score = max(0, 1.0 - (c.stops * 0.5))

        # Factor 5: Departure time preference (morning slightly preferred)
        try:
            hour = int(c.departure_time.split(":")[0])
            time_score = 1.0 if 7 <= hour <= 12 else 0.7 if hour < 7 else 0.5
        except (ValueError, IndexError):
            time_score = 0.5

        # Factor 6: Loyalty bonus (elite members get bonus on same-airline)
        loyalty_score = 1.0 if is_loyalty_elite else 0.5

        breakdown = {
            "price": round(price_score * w.get("weight_price", 0.30), 3),
            "cabin_class": round(cabin_score * w.get("weight_cabin_class", 0.20), 3),
            "arrival_delay": round(delay_score * w.get("weight_arrival_delay", 0.20), 3),
            "stops": round(stops_score * w.get("weight_stops", 0.10), 3),
            "departure_time": round(time_score * w.get("weight_departure_time", 0.10), 3),
            "loyalty_bonus": round(loyalty_score * w.get("weight_loyalty_bonus", 0.10), 3),
        }
        total = round(sum(breakdown.values()), 3)

        return c.model_copy(update={"score": total, "score_breakdown": breakdown})

    # ── OpenAI re-ranking (optional enhancement) ─────────────────────

    def _choose_with_openai(self, disruption: Disruption, candidates: list[dict]) -> dict | None:
        """Ask the model to rank candidates; it can propose but never authorize."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        
        client = OpenAI(api_key=api_key)
        prompt = {
            "task": "Select the best rebooking option for a disrupted traveler.",
            "disruption": disruption.model_dump(),
            "candidates": candidates,
            "rules": [
                "Prefer the lowest fare delta when cabin class is unchanged.",
                "You cannot authorize bookings or override policy.",
            ],
        }
        try:
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a travel disruption concierge."},
                    {"role": "user", "content": json.dumps(prompt)}
                ],
                response_format=OpenAIChoice,
                timeout=20,
            )
            choice = response.choices[0].message.parsed
            selected = next((item for item in candidates if item["flight"] == choice.candidate_flight), None)
            if selected:
                log_event(
                    agent="reasoning_agent",
                    sub_component="openai_ranker",
                    action="rank_candidates",
                    detail={"selected_flight": selected["flight"], "reason": choice.reason},
                    disruption_id=disruption.disruption_id,
                )
            return selected
        except Exception as e:
            # The deterministic scorer is the safe fallback for demo/API outages.
            print(f"OpenAI error: {e}")
            return None

    # ── Main proposal entry point ────────────────────────────────────

    def propose(self, disruption: Disruption, loyalty_elite: bool = True) -> RebookingProposal:
        """Score all candidates and select the best rebooking option."""
        scenario = disruption.reason
        raw_candidates = MOCK_CANDIDATES.get(scenario, MOCK_CANDIDATES["cancelled"])

        # Score every candidate
        scored = [self._score_candidate(c, is_loyalty_elite=loyalty_elite) for c in raw_candidates]
        scored.sort(key=lambda c: c.score, reverse=True)

        # Try OpenAI re-ranking on the top 3
        openai_pick = self._choose_with_openai(
            disruption,
            [c.model_dump() for c in scored[:3]],
        )
        reasoning_method = "deterministic"

        if openai_pick:
            best = next((c for c in scored if c.flight == openai_pick["flight"]), scored[0])
            reasoning_method = "openai_ranked"
        else:
            best = scored[0]

        # Check for rail alternative (§3.3 graceful degradation)
        route_key = "default"
        if disruption.segments:
            s = disruption.segments[0]
            route_key = f"{s.departure_airport}-{s.arrival_airport}"
        rail_alt = RAIL_ALTERNATIVES.get(route_key, RAIL_ALTERNATIVES.get("default"))

        proposal = RebookingProposal(
            disruption_id=disruption.disruption_id,
            candidate_flight=best.flight,
            fare_delta_usd=best.fare_delta_usd,
            cabin_class_same=best.cabin_class_same,
            all_candidates=[c.model_dump() for c in scored],
            reasoning_method=reasoning_method,
            rail_alternative=rail_alt,
        )

        log_event(
            agent="reasoning_agent",
            sub_component="scorer",
            action="propose_alternative",
            detail={
                "selected": best.model_dump(),
                "total_candidates": len(scored),
                "method": reasoning_method,
                "rail_alternative": rail_alt,
            },
            disruption_id=disruption.disruption_id,
        )
        return proposal
