"""
Run: python demo/run_demo.py
No API keys required -- everything is mocked but structurally real,
so this is your fallback if a live API dies mid-demo.

Exercises the full enhanced 5-agent pipeline:
- 3 disruption types (cancellation, missed connection, delay)
- 6-factor weighted scoring with ranked candidates
- Multiple benefit proposals per disruption
- Multi-channel comms with WhatsApp/SMS message previews
- Hash-chained audit trail with per-agent attribution
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Windows consoles default to cp1252, which cannot encode the box-drawing
# and emoji characters used below. Force UTF-8 output so the demo runs
# anywhere without needing PYTHONIOENCODING.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # Not a TextIOWrapper (e.g. in some test runners) — leave as-is.

from app.agents.monitor import MonitorAgent
from app.agents.reasoning import ReasoningAgent
from app.agents.rebooking import RebookingAgent
from app.agents.benefits import BenefitsAgent
from app.agents.comms import CommsAgent
from app.models import MemberProfile
from app.orchestrator import Orchestrator
from app.audit import AUDIT_LOG, verify_chain

SCENARIOS = [
    ("PNR-DEMO-001", "Flight Cancellation (JFK→ORD)"),
    ("PNR-DEMO-002", "Missed Connection (SFO→DEN→MIA)"),
    ("PNR-DEMO-003", "Severe Delay (LAX→ATL, 4 hours)"),
]


def run_pipeline(pnr: str, label: str, member: MemberProfile):
    """Run the full 5-agent pipeline for a single disruption."""
    monitor = MonitorAgent()
    reasoning = ReasoningAgent()
    orchestrator = Orchestrator()
    rebooking = RebookingAgent()
    benefits = BenefitsAgent()
    comms = CommsAgent()

    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")

    # ── 1. Monitor Agent ─────────────────────────────────────────────
    print("\n📡 MONITOR AGENT — Detecting disruption")
    disruption = monitor.detect(pnr=pnr)
    print(f"   Disruption ID : {disruption.disruption_id}")
    print(f"   Flight        : {disruption.original_flight}")
    print(f"   Reason        : {disruption.reason}")
    if disruption.segments:
        seg = disruption.segments[0]
        print(f"   Route          : {seg.departure_airport} → {seg.arrival_airport}")
        print(f"   Status         : {seg.status} ({seg.delay_minutes}min delay)")
    if disruption.connection_buffer_minutes is not None:
        print(f"   Connection     : {disruption.connection_buffer_minutes}min buffer vs {disruption.mct_minutes}min MCT")

    # ── 2. Reasoning Agent ───────────────────────────────────────────
    print("\n🧠 REASONING AGENT — Scoring candidates")
    proposal = reasoning.propose(disruption, loyalty_elite=(member.loyalty_status == "elite"))
    print(f"   Method         : {proposal.reasoning_method}")
    print(f"   Selected       : {proposal.candidate_flight} (${proposal.fare_delta_usd:.2f} delta)")
    if proposal.all_candidates:
        print(f"   All candidates ({len(proposal.all_candidates)}):")
        for i, c in enumerate(proposal.all_candidates[:5]):
            # Handle both RebookingCandidate objects and dicts
            _MISS = object()
            if hasattr(c, 'flight'):
                def g(k):
                    v = getattr(c, k, _MISS)
                    return v if v is not _MISS else c[k]
            else:
                g = lambda k: c[k]
            marker = "→" if g("flight") == proposal.candidate_flight else " "
            stops = g("stops")
            print(f"    {marker} {g('flight'):6s}  ${g('fare_delta_usd'):6.0f}  score={g('score'):.3f}  "
                  f"{'same' if g('cabin_class_same') else 'DOWN'}  {stops} stop{'s' if stops!=1 else ''}  +{g('arrival_delay_vs_original_min')}min")
    if proposal.rail_alternative:
        print(f"   🚆 Rail alt     : {proposal.rail_alternative}")

    # ── 3. Orchestrator (Policy Gate) ────────────────────────────────
    print("\n🛡️  ORCHESTRATOR — Policy gate")
    verdict = orchestrator.gate(proposal)
    icon = {"auto_approve": "✅", "escalate": "⚠️", "blocked": "🚫"}[verdict.verdict]
    print(f"   Verdict        : {icon} {verdict.verdict}")
    print(f"   Rule           : {verdict.policy_rule_id}")

    # ── 4. Rebooking Agent ───────────────────────────────────────────
    print("\n💳 REBOOKING AGENT — Executing")
    result = rebooking.execute(proposal, verdict)
    print(f"   Status         : {result['status']}")
    if result.get("payment_detail"):
        pd = result["payment_detail"]
        print(f"   Token          : {pd.get('token', 'N/A')}")
        print(f"   Merchant       : {pd.get('merchant', 'N/A')}")

    # ── 5. Benefits Agent ────────────────────────────────────────────
    print("\n🎁 BENEFITS AGENT — Filing eligible claims")
    all_benefits = benefits.propose_all(disruption, member)
    benefit_results = benefits.execute_all(all_benefits, orchestrator)
    for br in benefit_results:
        bp = br["proposal"]
        bres = br["result"]
        icon = {"trip_delay_claim": "🕐", "lounge_access": "🛋️", "meal_comp": "🍽️", "hotel_comp": "🏨"}.get(bp["benefit_type"], "📋")
        status = bres.get("status", "unknown")
        print(f"   {icon} {bp['benefit_type']:20s} ${bp['estimated_value_usd']:>7.0f}  [{status}]  "
              f"{bp.get('policy_reference', '')}")

    # ── 6. Comms Agent ───────────────────────────────────────────────
    print("\n📱 COMMS AGENT — Notifications queued")
    notification = comms.notify(disruption, result, benefit_results[0]["result"] if benefit_results else {}, member)
    channels = notification.get("channels", {})
    for ch_name in channels:
        ch = channels[ch_name]
        print(f"   [{ch_name.upper():9s}] {ch.get('subject', '')}")
    if channels.get("whatsapp"):
        print(f"\n   ── WhatsApp Preview ──")
        for line in channels["whatsapp"]["body"].split("\n"):
            print(f"   │ {line}")


if __name__ == "__main__":
    member = MemberProfile(
        member_id="mbr_demo_001",
        email="traveler@example.com",
        card_tier="platinum",
        loyalty_status="gold",
    )

    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║       AUTONOMOUS TRAVEL-DISRUPTION CONCIERGE — FULL DEMO           ║")
    print("║       5-Agent Crew · Policy-Gated · Visa Intelligent Commerce      ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print(f"\n👤 Member: {member.member_id} | Card: {member.card_tier} | Loyalty: {member.loyalty_status}")

    for pnr, label in SCENARIOS:
        run_pipeline(pnr, label, member)

    # ── Audit Integrity ──────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  🔗 AUDIT TRAIL INTEGRITY")
    print(f"{'='*70}")
    valid = verify_chain()
    print(f"   Hash chain     : {'✅ VALID — tamper-evident, append-only' if valid else '❌ INVALID — chain broken!'}")

    # Reuse the audit module's real path (data/audit_log.jsonl) instead of
    # guessing a root-level log that never exists.
    log_path = AUDIT_LOG
    try:
        with open(log_path, encoding="utf-8") as f:
            count = sum(1 for _ in f)
        print(f"   Total entries  : {count}")
    except OSError:
        print("   Total entries  : (unable to read)")

    print(f"\n{'='*70}")
    print(f"  ✅ Demo complete. All 5 agents exercised across 3 disruption types.")
    print(f"{'='*70}\n")
