"""Server-side Prava Sandbox client.

The secret key is used only here. Browser code receives an iframe URL and
never receives a Prava secret, Visa network token, or dynamic CVV.
"""
import os
import time
from decimal import Decimal
from typing import Any

import requests

from app.models import PravaSession
from app.audit import log_event

PRAVA_BACKEND_URL = os.getenv("PRAVA_BACKEND_URL", "https://sandbox.api.prava.space")


class PravaClient:
    def __init__(self) -> None:
        # PRAVA_API_KEY is kept as a backwards-compatible alias for the
        # existing scaffold's environment file.
        self.secret_key = os.getenv("PRAVA_SECRET_KEY") or os.getenv("PRAVA_API_KEY")
        self.backend_url = os.getenv("PRAVA_BACKEND_URL", PRAVA_BACKEND_URL).rstrip("/")
        self.callback_url = os.getenv("PRAVA_CALLBACK_URL", "").strip()

    def _headers(self) -> dict[str, str]:
        if not self.secret_key:
            raise RuntimeError("Prava secret key is not configured.")
        if not self.secret_key.startswith("sk_test_"):
            raise RuntimeError("This dashboard only permits a Prava sandbox sk_test_ key.")
        return {"Authorization": f"Bearer {self.secret_key}", "Content-Type": "application/json"}

    @staticmethod
    def _raise_for_api_error(response: requests.Response) -> None:
        if response.ok:
            return
        try:
            message = response.json().get("error", {}).get("message")
        except ValueError:
            message = None
        raise RuntimeError(message or f"Prava API request failed (HTTP {response.status_code}).")

    def create_session(
        self, *, user_id: str, user_email: str, amount_usd: float, description: str, merchant_name: str
    ) -> PravaSession:
        """Create one Prava session for an approved travel-rebooking proposal."""
        if self.callback_url and not self.callback_url.startswith("https://"):
            raise RuntimeError("PRAVA_CALLBACK_URL must use an HTTPS public URL.")

        payload: dict[str, Any] = {
            "user_id": user_id,
            "user_email": user_email,
            "total_amount": f"{Decimal(str(amount_usd)):.2f}",
            "currency": "USD",
            "description": description,
            # Explicitly use Prava's hosted checkout flow. Card collection and
            # passkey enrollment stay on Prava's PCI-scoped surface.
            "integration_type": "full_checkout",
            "external_order_ref": f"travel-rebooking-{user_id}",
            "purchase_context": [{
                # This names the intended travel merchant; it does not itself
                # place an airline booking. That remains a separate integration.
                "merchant_details": {
                    "name": merchant_name,
                    "url": "https://www.aa.com",
                    "country_code_iso2": "US",
                    "category_code": "4511",
                    "category": "Airlines",
                },
                "product_details": [{
                    "description": description,
                    "unit_price": f"{Decimal(str(amount_usd)):.2f}",
                    "quantity": 1,
                }],
                "effective_until_minutes": 15,
            }],
        }
        if self.callback_url:
            payload["callback_url"] = self.callback_url
        response = requests.post(
            f"{self.backend_url}/v1/sessions", headers=self._headers(), json=payload, timeout=20
        )
        self._raise_for_api_error(response)
        data = response.json()
        session = PravaSession(
            session_id=data["session_id"],
            iframe_url=data["iframe_url"],
            expires_at=data.get("expires_at"),
        )
        log_event(
            agent="rebooking_agent",
            sub_component="prava_pay",
            action="create_payment_session",
            detail={"session_id": session.session_id, "amount_usd": amount_usd, "merchant": merchant_name},
            policy_verdict="awaiting_member_passkey_approval",
        )
        return session

    def payment_status(self, session_id: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.backend_url}/v1/sessions/{session_id}/payment-result",
            headers={"Authorization": f"Bearer {self.secret_key}"},
            params={"_t": str(int(time.time() * 1000))},
            timeout=20,
        )
        self._raise_for_api_error(response)
        payload = response.json()
        # Do not ever pass one-time network credentials to the browser.
        transactions = payload.get("transactions") or []
        transaction = transactions[0] if transactions else {}
        error = transaction.get("error") or {}
        return {
            "session_id": session_id,
            "status": payload.get("status", "pending"),
            "error": {"code": error.get("code"), "message": error.get("message")} if error else None,
        }

    def health(self) -> bool:
        try:
            return requests.get(f"{self.backend_url}/health", timeout=10).ok
        except requests.RequestException:
            return False
