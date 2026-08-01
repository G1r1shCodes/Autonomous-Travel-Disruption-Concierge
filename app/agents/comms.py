"""Comms Agent — multi-channel notifications with before/after comparison.

Matches §3.4 / §4.2 of the pitch doc:
- Multi-channel support: dashboard, WhatsApp, SMS
- Before/after itinerary comparison
- Approve/decline action buttons for escalated proposals — delivered as
  Twilio WhatsApp URL buttons (persistent_action) and an SMS link
- Delivery is env-gated: without Twilio credentials the payloads remain
  structurally-real previews (graceful degradation for demo/offline runs)
"""
import os
from twilio.rest import Client
from app.audit import log_event
from app.models import Disruption, CommsNotification, MemberProfile


class CommsAgent:
    """Queues and (optionally) delivers member-facing updates across channels."""

    # ── Template builders ────────────────────────────────────────────

    def _build_before_after(self, disruption: Disruption, rebooking: dict) -> tuple[dict, dict]:
        """Build before/after itinerary comparison data."""
        before = {
            "flight": disruption.original_flight,
            "status": disruption.reason.replace("_", " ").title(),
            "route": "",
        }
        if disruption.segments:
            seg = disruption.segments[0]
            before["route"] = f"{seg.departure_airport} → {seg.arrival_airport}"
            before["departure"] = seg.scheduled_departure
            before["arrival"] = seg.scheduled_arrival

        after = {
            "flight": rebooking.get("flight", rebooking.get("candidate_flight", "—")),
            "status": rebooking.get("status", "pending"),
        }
        return before, after

    def _format_whatsapp(
        self, disruption: Disruption, before: dict, after: dict,
        benefit_summary: str, is_escalated: bool,
        approve_url: str = "", decline_url: str = ""
    ) -> str:
        """Build a WhatsApp-style message template (§3.4)."""
        lines = [
            f"✈️ *Travel Disruption Alert*",
            f"",
            f"Your flight *{before['flight']}* ({before.get('route', '')}) has been *{before['status']}*.",
            f"",
        ]
        if after["status"] in ("booked", "payment_authorization_pending", "awaiting_member_approval"):
            lines.extend([
                f"🔄 *Rebooked:* {after['flight']}",
                f"",
            ])
        if benefit_summary:
            lines.extend([
                f"💳 *Benefits:* {benefit_summary}",
                f"",
            ])
        if is_escalated and approve_url:
            lines.extend([
                f"👆 This rebooking needs your approval:",
                f"✅ Approve: {approve_url}",
                f"❌ Decline: {decline_url or approve_url.replace('action=approve', 'action=decline')}",
            ])
        else:
            lines.append("No action required — your concierge handled everything.")

        return "\n".join(lines)

    def _format_sms(self, disruption: Disruption, after: dict, is_escalated: bool,
                    approve_url: str = "", decline_url: str = "") -> str:
        """Build a concise SMS fallback message."""
        action = "Approval needed" if is_escalated else "Auto-rebooked"
        if is_escalated and approve_url:
            link = (f"Decide: Approve {approve_url} | "
                    f"Decline {decline_url or approve_url.replace('action=approve', 'action=decline')}")
        else:
            link = "Details: https://concierge.example.com/status"
        return (
            f"Flight {disruption.original_flight} {disruption.reason.replace('_', ' ')}. "
            f"{action}: {after.get('flight', '—')}. {link}"
        )

    # ── Delivery (env-gated Twilio) ──────────────────────────────────

    @staticmethod
    def _twilio() -> Client | None:
        """Return a Twilio client when credentials exist, else None."""
        account = os.getenv("TWILIO_ACCOUNT_SID")
        token = os.getenv("TWILIO_AUTH_TOKEN")
        return Client(account, token) if account and token else None

    def _send_whatsapp(self, body: str, approve_url: str = "", decline_url: str = "") -> bool:
        """Send the WhatsApp message; URL buttons when escalated. Never raises."""
        client = self._twilio()
        wa_from = os.getenv("TWILIO_WHATSAPP_FROM")
        member_phone = os.getenv("MEMBER_WHATSAPP_NUMBER")
        if not (client and wa_from and member_phone):
            return False
        try:
            kwargs: dict = {"body": body, "from_": wa_from, "to": member_phone}
            if approve_url:
                # Twilio WhatsApp URL buttons (max 3) — one-tap approve/decline.
                kwargs["persistent_action"] = [approve_url, decline_url or approve_url]
            client.messages.create(**kwargs)
            return True
        except Exception as e:
            print(f"Twilio WhatsApp failed: {e}")
            return False

    def _send_sms(self, body: str) -> bool:
        """Send the SMS fallback. Never raises."""
        client = self._twilio()
        sms_from = os.getenv("TWILIO_PHONE_NUMBER")
        member_phone = os.getenv("MEMBER_PHONE_NUMBER")
        if not (client and sms_from and member_phone):
            return False
        try:
            client.messages.create(body=body, from_=sms_from, to=member_phone)
            return True
        except Exception as e:
            print(f"Twilio SMS failed: {e}")
            return False

    # ── Public entry point ───────────────────────────────────────────

    def notify(self, disruption: Disruption, rebooking: dict, benefit: dict,
               member: MemberProfile = None, proposal_id: str = "",
               public_base_url: str = "") -> dict:
        """Prepare and deliver multi-channel notifications.

        Returns per-channel payloads plus a ``delivered`` map (channel → bool).
        ``proposal_id`` + ``public_base_url`` are needed to build the live
        approve/decline URLs for escalated proposals.
        """
        if member is None:
            member = MemberProfile()

        before, after = self._build_before_after(disruption, rebooking)
        is_escalated = rebooking.get("status") == "awaiting_member_approval"

        # Build benefit summary line
        benefit_status = benefit.get("status", "")
        benefit_type = benefit.get("benefit_type", benefit.get("proposal", {}).get("benefit_type", ""))
        benefit_value = benefit.get("eligible_amount_usd", benefit.get("estimated_value_usd", ""))
        benefit_summary = ""
        if benefit_status == "submitted":
            benefit_summary = f"{benefit_type.replace('_', ' ').title()} claim filed (${benefit_value})"
        elif benefit_status == "awaiting_member_approval":
            benefit_summary = f"{benefit_type.replace('_', ' ').title()} pending your approval"

        # Live approve/decline URLs for escalated proposals
        base = (public_base_url or os.getenv("PUBLIC_BASE_URL", "")).rstrip("/")
        approve_url = decline_url = ""
        if is_escalated and proposal_id and base:
            approve_url = f"{base}/api/comms/decision?proposal_id={proposal_id}&action=approve"
            decline_url = f"{base}/api/comms/decision?proposal_id={proposal_id}&action=decline"

        # Dashboard notification (always sent)
        dashboard_msg = (
            f"Disruption {disruption.original_flight} ({disruption.reason.replace('_', ' ')}): "
            f"rebooking → {after.get('flight', '—')} [{rebooking.get('status', 'pending')}]"
        )
        if benefit_summary:
            dashboard_msg += f" | {benefit_summary}"

        # WhatsApp message (§3.4 primary channel)
        whatsapp_msg = self._format_whatsapp(
            disruption, before, after, benefit_summary, is_escalated, approve_url, decline_url
        )

        # SMS fallback
        sms_msg = self._format_sms(disruption, after, is_escalated, approve_url, decline_url)

        # Deliver via Twilio when configured (preview-only otherwise)
        delivered = {}
        if whatsapp_msg:
            delivered["whatsapp"] = self._send_whatsapp(whatsapp_msg, approve_url, decline_url)
        if sms_msg:
            delivered["sms"] = self._send_sms(sms_msg)

        actions = (
            [{"label": "Approve", "action": "approve", "url": approve_url},
             {"label": "Decline", "action": "decline", "url": decline_url}]
            if is_escalated else []
        )

        notifications = [
            CommsNotification(
                channel="dashboard",
                recipient=member.member_id,
                subject=f"Flight {disruption.original_flight} — {disruption.reason.replace('_', ' ').title()}",
                body=dashboard_msg,
                before_itinerary=before,
                after_itinerary=after,
                actions=actions,
            ),
            CommsNotification(
                channel="whatsapp",
                recipient=member.email,
                subject="Travel Disruption Alert",
                body=whatsapp_msg,
                before_itinerary=before,
                after_itinerary=after,
                actions=actions,
            ),
            CommsNotification(
                channel="sms",
                recipient=member.email,
                subject="Flight Update",
                body=sms_msg,
            ),
        ]

        log_event(
            agent="comms_agent",
            sub_component="member_notification",
            action="queue_notifications",
            detail={
                "channels": [n.channel for n in notifications],
                "is_escalated": is_escalated,
                "has_benefit": bool(benefit_summary),
                "before_flight": before.get("flight"),
                "after_flight": after.get("flight"),
                "delivered": delivered,
            },
            disruption_id=disruption.disruption_id,
        )

        return {
            "status": "queued",
            "channels": {n.channel: n.model_dump() for n in notifications},
            "message": dashboard_msg,
            "delivered": delivered,
        }
