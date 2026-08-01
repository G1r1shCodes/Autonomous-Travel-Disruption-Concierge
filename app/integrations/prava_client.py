"""
Prava payments/trust layer client.

THIS IS THE FILE TO REPLACE WITH REAL PRAVA CALLS.
Point Claude Code at https://github.com/Prava-Payments/prava-skills and ask
it to "integrate Prava payments here" -- don't hand-write the endpoints,
the skill repo exists specifically so an agent gets this right on the
first try.

Real flow (per docs.prava.space): open a session -> Prava checks the
request against the member's standing mandate -> auto-issues a one-time
token, OR sends a passkey (Face ID/Touch ID) prompt if outside the mandate
-> agent uses the token to complete checkout at the merchant.

This mock preserves that exact shape so swapping in the real SDK later
is a one-file change, not a re-architecture.
"""
import os
from app.models import PaymentResult
from app.audit import log_event

MANDATE_MAX_USD = float(os.getenv("PRAVA_MANDATE_MAX_USD", "75"))


class PravaClient:
    def request_payment_token(self, merchant: str, amount_usd: float) -> PaymentResult:
        if amount_usd <= MANDATE_MAX_USD:
            result = PaymentResult(
                status="auto_approved",
                token="tok_mock_" + os.urandom(4).hex(),
                merchant=merchant,
                amount_usd=amount_usd,
            )
        else:
            # In the real flow this triggers a passkey push to the member's
            # device instead of failing outright. Mocked here as a status.
            result = PaymentResult(
                status="passkey_required",
                merchant=merchant,
                amount_usd=amount_usd,
            )

        log_event(
            agent="rebooking_agent",
            sub_component="prava_pay",
            action="issue_payment_token",
            detail=result.model_dump(),
            policy_verdict=result.status,
        )
        return result
