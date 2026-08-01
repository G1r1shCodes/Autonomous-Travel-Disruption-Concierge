"""FastAPI dashboard for the travel-disruption demo.

Run with: uvicorn app.main:app --reload
"""
from __future__ import annotations

import os
from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

load_dotenv()

from app.agents.monitor import MonitorAgent
from app.agents.reasoning import ReasoningAgent
from app.agents.benefits import BenefitsAgent
from app.agents.comms import CommsAgent
from app.integrations.prava_client import PravaClient
from app.models import RebookingProposal, MemberProfile
from app.models import MemberDecision
from app.orchestrator import Orchestrator
from app.audit import chain_status, recent_entries, log_event

app = FastAPI(title="Travel Disruption Concierge", version="0.2.0")
_proposals: dict[str, dict] = {}


class DemoRequest(BaseModel):
    scenario: Literal["auto", "escalate", "blocked"] = "auto"
    pnr: str = "PNR-DEMO-001"


class StartPaymentRequest(BaseModel):
    member_email: str
    member_approved: bool = False


# ── Scenario helpers ─────────────────────────────────────────────────

SCENARIO_PNRS = {
    "auto": "PNR-DEMO-001",        # cancelled → $42 auto-approve
    "escalate": "PNR-DEMO-002",    # missed connection → $55 but override to $120
    "blocked": "PNR-DEMO-003",     # delayed → override to $200
}


def _proposal_for(scenario: str) -> tuple:
    pnr = SCENARIO_PNRS.get(scenario, "PNR-DEMO-001")
    disruption = MonitorAgent().detect(pnr=pnr)
    proposal = ReasoningAgent().propose(disruption)

    if scenario == "escalate":
        proposal = proposal.model_copy(update={
            "candidate_flight": "DL551", "fare_delta_usd": 120.0
        })
    elif scenario == "blocked":
        proposal = proposal.model_copy(update={"fare_delta_usd": 200.0})

    verdict = Orchestrator().gate(proposal)
    return disruption, proposal, verdict.model_dump()


# ── API endpoints ────────────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
def dashboard() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/prava/callback", response_class=HTMLResponse)
def prava_callback() -> str:
    """Safe landing page after Prava's hosted checkout redirects the member."""
    return """<!doctype html><title>Returning to concierge</title>
    <main style='font:16px system-ui;max-width:40rem;margin:5rem auto;padding:1.5rem'>
    <h1>Secure approval received</h1>
    <p>You may close this tab and return to the Travel Disruption Concierge.</p>
    </main>"""


@app.get("/api/health")
def health() -> dict:
    return {"prava_sandbox_reachable": PravaClient().health()}


@app.post("/api/proposals/demo")
def create_demo_proposal(request: DemoRequest) -> dict:
    disruption, proposal, verdict = _proposal_for(request.scenario)
    proposal_id = str(uuid4())
    member = MemberProfile()
    benefits = BenefitsAgent()
    orchestrator = Orchestrator()

    # Multiple benefit proposals
    all_benefit_proposals = benefits.propose_all(disruption, member)
    benefit_results = benefits.execute_all(all_benefit_proposals, orchestrator)

    # Primary benefit (backward compat)
    primary_benefit = benefits.propose(disruption)
    primary_verdict = orchestrator.gate_benefit(primary_benefit)
    primary_result = benefits.execute(primary_benefit, primary_verdict)

    # Comms notification — escalated proposals get live approve/decline
    # links (WhatsApp/SMS/dashboard) resolved by the comms decision webhook.
    notify_status = "awaiting_member_approval" if verdict["verdict"] == "escalate" else (
        "payment_authorization_pending" if verdict["verdict"] != "blocked" else "blocked"
    )
    public_base = os.getenv("PUBLIC_BASE_URL", "").strip()
    if not public_base and os.getenv("PRAVA_CALLBACK_URL"):
        # Derive the site origin from the Prava callback URL: keep
        # scheme://host and drop any callback path segment.
        callback = os.getenv("PRAVA_CALLBACK_URL", "").strip().rstrip("/")
        scheme_end = callback.find("://")
        if scheme_end != -1:
            host_start = scheme_end + 3
            host_end = callback.find("/", host_start)
            public_base = callback if host_end == -1 else callback[:host_end]
        else:
            public_base = callback

    # Store the proposal first so a WhatsApp button tapped in the same
    # instant resolves against the checkpoint instead of 404ing.
    _proposals[proposal_id] = {"proposal": proposal, "verdict": verdict, "decision": None}

    notification = CommsAgent().notify(
        disruption,
        {"status": notify_status, "flight": proposal.candidate_flight},
        primary_result,
        member,
        proposal_id=proposal_id,
        public_base_url=public_base,
    )

    return {
        "proposal_id": proposal_id,
        "disruption": disruption.model_dump(),
        "proposal": proposal.model_dump(),
        "verdict": verdict,
        "benefit": {
            "proposal": primary_benefit.model_dump(),
            "verdict": primary_verdict.model_dump(),
            "result": primary_result,
        },
        "all_benefits": benefit_results,
        "notification": notification,
        "member": member.model_dump(),
    }


def _record_decision(proposal_id: str, decision: str) -> dict:
    """Shared member checkpoint used by the dashboard and the WhatsApp webhook."""
    saved = _proposals.get(proposal_id)
    if not saved:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    verdict = saved["verdict"]["verdict"]
    if verdict != "escalate":
        raise HTTPException(status_code=409, detail="Only escalated proposals require a member decision.")
    if saved.get("decision") is not None:
        # First decision wins — a double-tap or stale link never re-runs the
        # checkpoint or logs a second approval/decline event.
        prior = saved["decision"]
        return {
            "proposal_id": proposal_id,
            "decision": prior,
            "already_recorded": True,
            "next_step": "start_prava" if prior == "approve" else "human_handoff",
        }
    saved["decision"] = decision
    action = "member_approved_proposal" if decision == "approve" else "member_declined_proposal"
    log_event("orchestrator", "human_checkpoint", action, {"proposal_id": proposal_id})
    return {
        "proposal_id": proposal_id,
        "decision": decision,
        "next_step": "start_prava" if decision == "approve" else "human_handoff",
    }


def _decision_page(title: str, message: str, ok: bool) -> str:
    """Small confirmation page shown after a WhatsApp/SMS one-tap decision."""
    emoji = "✅" if ok else "⚠️"
    return f"""<!doctype html><title>{title}</title>
    <main style='font:16px system-ui;max-width:40rem;margin:5rem auto;padding:1.5rem'>
    <h1>{emoji} {title}</h1>
    <p>{message}</p>
    <p style='color:#666'>You may close this tab and return to the Travel Disruption Concierge.</p>
    </main>"""


@app.post("/api/proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: str, request: MemberDecision) -> dict:
    """Record the reusable member checkpoint before any escalated payment."""
    return _record_decision(proposal_id, request.decision)


@app.get("/api/comms/decision", response_class=HTMLResponse)
def comms_decision(proposal_id: str, action: Literal["approve", "decline"] = "approve") -> str:
    """Landing page for Twilio WhatsApp/SMS approve/decline buttons."""
    try:
        _record_decision(proposal_id, action)
    except HTTPException as error:
        return _decision_page("Decision not recorded", error.detail, ok=False)
    if action == "approve":
        return _decision_page(
            "Rebooking approved",
            "Your concierge is completing the rebooking through Prava.",
            ok=True,
        )
    return _decision_page(
        "Rebooking declined",
        "No payment was made — a human agent will reach out.",
        ok=True,
    )


@app.get("/api/audit/status")
def audit_status() -> dict:
    return chain_status()


@app.get("/api/audit/entries")
def audit_entries(limit: int = 30) -> list[dict]:
    """Return recent audit log entries for the dashboard viewer."""
    return recent_entries(limit=min(limit, 100))


@app.post("/api/proposals/{proposal_id}/start-prava")
def start_prava_payment(proposal_id: str, request: StartPaymentRequest) -> dict:
    saved = _proposals.get(proposal_id)
    if not saved:
        raise HTTPException(status_code=404, detail="Proposal not found. Generate a new demo proposal.")
    proposal: RebookingProposal = saved["proposal"]
    verdict = saved["verdict"]["verdict"]
    if verdict == "blocked":
        raise HTTPException(status_code=409, detail="Policy blocks this proposal; no payment session can be created.")
    if verdict == "escalate" and saved.get("decision") != "approve" and not request.member_approved:
        raise HTTPException(status_code=409, detail="This proposal needs the member's approval before starting Prava.")
    if "@" not in request.member_email:
        raise HTTPException(status_code=422, detail="Enter a valid member email address.")

    try:
        session = PravaClient().create_session(
            user_id=f"travel-demo-{uuid4().hex}",
            user_email=request.member_email,
            amount_usd=proposal.fare_delta_usd,
            description=f"Travel rebooking: {proposal.candidate_flight}",
            merchant_name="American Airlines",
        )
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return session.model_dump()


@app.get("/api/prava/sessions/{session_id}")
def prava_payment_status(session_id: str) -> dict:
    try:
        return PravaClient().payment_status(session_id)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


