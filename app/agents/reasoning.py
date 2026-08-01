"""Reasoning Agent -- deterministic candidates with optional OpenAI ranking."""
import json
import os

import requests
from app.models import Disruption, RebookingProposal
from app.audit import log_event


class ReasoningAgent:
    def _choose_with_openai(self, disruption: Disruption, candidates: list[dict]) -> dict | None:
        """Ask the model to rank candidates; it can propose but never authorize."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        prompt = {
            "task": "Select the best rebooking option for a disrupted traveler.",
            "disruption": disruption.model_dump(),
            "candidates": candidates,
            "rules": [
                "Prefer the lowest fare delta when cabin class is unchanged.",
                "Return JSON only: {\"candidate_flight\": string, \"reason\": string}.",
                "You cannot authorize bookings or override policy.",
            ],
        }
        try:
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "gpt-5.6-terra", "input": json.dumps(prompt)},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            output_text = payload.get("output_text", "")
            if not output_text:
                for message in payload.get("output", []):
                    for content in message.get("content", []):
                        if content.get("type") == "output_text":
                            output_text = content.get("text", "")
                            break
                    if output_text:
                        break
            choice = json.loads(output_text)
            selected = next((item for item in candidates if item["flight"] == choice.get("candidate_flight")), None)
            if selected:
                log_event(
                    agent="reasoning_agent",
                    sub_component="openai_ranker",
                    action="rank_candidates",
                    detail={"selected_flight": selected["flight"], "reason": choice.get("reason", "")},
                )
            return selected
        except (requests.RequestException, ValueError, json.JSONDecodeError, StopIteration):
            # The deterministic scorer is the safe fallback for demo/API outages.
            return None

    def propose(self, disruption: Disruption) -> RebookingProposal:
        candidates = [
            {"flight": "AA318", "fare_delta_usd": 42, "cabin_class_same": True},
            {"flight": "DL551", "fare_delta_usd": 120, "cabin_class_same": True},
        ]
        best = self._choose_with_openai(disruption, candidates) or min(
            candidates, key=lambda candidate: candidate["fare_delta_usd"]
        )

        proposal = RebookingProposal(
            disruption_id=disruption.disruption_id,
            candidate_flight=best["flight"],
            fare_delta_usd=best["fare_delta_usd"],
            cabin_class_same=best["cabin_class_same"],
        )
        log_event(
            agent="reasoning_agent",
            sub_component="scorer",
            action="propose_alternative",
            detail=proposal.model_dump(),
        )
        return proposal
