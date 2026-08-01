"""Comms Agent — multi-channel notifications with before/after comparison.

Matches §3.4 / §4.2 of the pitch doc:
- Multi-channel support: dashboard, WhatsApp, SMS
- Before/after itinerary comparison
- Approve/decline action buttons for escalated proposals
- WhatsApp/SMS message templates (structurally real, delivery mocked)
"""
from app.audit import log_event
from app.models import Disruption, CommsNotification, MemberProfile


class CommsAgent:
    """Queues member-facing updates across multiple channels."""

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
        benefit_summary: str, is_escalated: bool, approve_url: str = ""
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
                f"✅ Approve: {approve_url}?action=approve",
                f"❌ Decline: {approve_url}?action=decline",
            ])
        else:
            lines.append("No action required — your concierge handled everything.")

        return "\n".join(lines)

    def _format_sms(self, disruption: Disruption, after: dict, is_escalated: bool) -> str:
        """Build a concise SMS fallback message."""
        action = "Approval needed" if is_escalated else "Auto-rebooked"
        return (
            f"Flight {disruption.original_flight} {disruption.reason.replace('_', ' ')}. "
            f"{action}: {after.get('flight', '—')}. "
            f"Details: https://concierge.example.com/status"
        )

    def notify(self, disruption: Disruption, rebooking: dict, benefit: dict,
               member: MemberProfile = None) -> dict:
        """Prepare and queue multi-channel notifications.

        Returns a dict with per-channel message payloads — structurally
        identical to what would be sent via Twilio WhatsApp/SMS APIs.
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

        approve_url = "https://concierge.example.com/approve"

        # Dashboard notification (always sent)
        dashboard_msg = (
            f"Disruption {disruption.original_flight} ({disruption.reason.replace('_', ' ')}): "
            f"rebooking → {after.get('flight', '—')} [{rebooking.get('status', 'pending')}]"
        )
        if benefit_summary:
            dashboard_msg += f" | {benefit_summary}"

        # WhatsApp message (§3.4 primary channel)
        whatsapp_msg = self._format_whatsapp(
            disruption, before, after, benefit_summary, is_escalated, approve_url
        )

        # SMS fallback
        sms_msg = self._format_sms(disruption, after, is_escalated)

        notifications = [
            CommsNotification(
                channel="dashboard",
                recipient=member.member_id,
                subject=f"Flight {disruption.original_flight} — {disruption.reason.replace('_', ' ').title()}",
                body=dashboard_msg,
                before_itinerary=before,
                after_itinerary=after,
                actions=[{"label": "Approve", "action": "approve"}, {"label": "Decline", "action": "decline"}]
                if is_escalated else [],
            ),
            CommsNotification(
                channel="whatsapp",
                recipient=member.email,
                subject="Travel Disruption Alert",
                body=whatsapp_msg,
                before_itinerary=before,
                after_itinerary=after,
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
            },
            disruption_id=disruption.disruption_id,
        )

        return {
            "status": "queued",
            "channels": {n.channel: n.model_dump() for n in notifications},
            "message": dashboard_msg,
        }
