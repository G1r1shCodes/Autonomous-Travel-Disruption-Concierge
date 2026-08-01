"""FastAPI dashboard for the travel-disruption demo.

Run with: uvicorn app.main:app --reload
"""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

load_dotenv()

from app.agents.monitor import MonitorAgent
from app.agents.reasoning import ReasoningAgent
from app.agents.benefits import BenefitsAgent
from app.agents.comms import CommsAgent
from app.integrations.prava_client import PravaClient
from app.models import RebookingProposal
from app.orchestrator import Orchestrator

app = FastAPI(title="Travel Disruption Concierge", version="0.1.0")
_proposals: dict[str, dict] = {}


class DemoRequest(BaseModel):
    scenario: Literal["auto", "escalate", "blocked"] = "auto"


class StartPaymentRequest(BaseModel):
    member_email: str
    member_approved: bool = False


def _proposal_for(scenario: str) -> tuple:
    disruption = MonitorAgent().detect(pnr="PNR-DEMO-001")
    proposal = ReasoningAgent().propose(disruption)
    if scenario == "escalate":
        proposal = proposal.model_copy(update={"candidate_flight": "DL551", "fare_delta_usd": 120.0})
    elif scenario == "blocked":
        proposal = proposal.model_copy(update={"fare_delta_usd": 200.0})
    verdict = Orchestrator().gate(proposal)
    return disruption, proposal, verdict.model_dump()


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD_HTML


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
    benefits = BenefitsAgent()
    benefit_proposal = benefits.propose(disruption)
    benefit_verdict = Orchestrator().gate_benefit(benefit_proposal)
    benefit_result = benefits.execute(benefit_proposal, benefit_verdict)
    notification = CommsAgent().notify(
        disruption,
        {"status": "payment_authorization_pending" if verdict["verdict"] != "blocked" else "blocked"},
        benefit_result,
    )
    _proposals[proposal_id] = {"proposal": proposal, "verdict": verdict}
    return {
        "proposal_id": proposal_id,
        "disruption": disruption.model_dump(),
        "proposal": proposal.model_dump(),
        "verdict": verdict,
        "benefit": {"proposal": benefit_proposal.model_dump(), "verdict": benefit_verdict.model_dump(), "result": benefit_result},
        "notification": notification,
    }


@app.post("/api/proposals/{proposal_id}/start-prava")
def start_prava_payment(proposal_id: str, request: StartPaymentRequest) -> dict:
    saved = _proposals.get(proposal_id)
    if not saved:
        raise HTTPException(status_code=404, detail="Proposal not found. Generate a new demo proposal.")
    proposal: RebookingProposal = saved["proposal"]
    verdict = saved["verdict"]["verdict"]
    if verdict == "blocked":
        raise HTTPException(status_code=409, detail="Policy blocks this proposal; no payment session can be created.")
    if verdict == "escalate" and not request.member_approved:
        raise HTTPException(status_code=409, detail="This proposal needs the member's approval before starting Prava.")
    if "@" not in request.member_email:
        raise HTTPException(status_code=422, detail="Enter a valid member email address.")

    try:
        session = PravaClient().create_session(
            # A test session is single-use. A fresh sandbox customer/order
            # identity avoids carrying a partial enrollment from a failed
            # passkey attempt into the next demo retry.
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


DASHBOARD_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Travel Disruption Concierge</title>
  <style>
    :root { color-scheme: dark; --ink: oklch(0.93 0.014 247); --muted: oklch(0.72 0.025 247); --canvas: oklch(0.19 0.025 248); --surface: oklch(0.245 0.026 248); --line: oklch(0.39 0.025 248); --accent: oklch(0.76 0.15 190); --good: oklch(0.75 0.16 150); --warn: oklch(0.8 0.15 80); --bad: oklch(0.67 0.19 25); }
    * { box-sizing: border-box; } body { margin: 0; background: var(--canvas); color: var(--ink); font: 15px/1.5 Inter, ui-sans-serif, system-ui, sans-serif; }
    main { max-width: 980px; margin: 0 auto; padding: 48px 24px 72px; } header { display: flex; justify-content: space-between; align-items: start; gap: 24px; border-bottom: 1px solid var(--line); padding-bottom: 28px; }
    h1 { font-size: 28px; letter-spacing: -.025em; margin: 0 0 6px; } h2 { font-size: 17px; margin: 0 0 12px; } p { margin: 0; color: var(--muted); max-width: 68ch; } .status { font-size: 13px; color: var(--muted); white-space: nowrap; }
    .workspace { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(280px, .75fr); gap: 24px; margin-top: 28px; } section { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 24px; }
    .choices { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0 22px; } button { appearance: none; border: 1px solid var(--line); color: var(--ink); background: transparent; padding: 9px 12px; border-radius: 8px; font: inherit; cursor: pointer; } button:hover, button:focus-visible { border-color: var(--accent); outline: none; } button.primary { background: var(--accent); color: oklch(0.19 0.025 248); border-color: var(--accent); font-weight: 700; } button:disabled { opacity: .55; cursor: not-allowed; }
    dl { display: grid; grid-template-columns: max-content 1fr; gap: 8px 18px; margin: 18px 0 0; } dt { color: var(--muted); } dd { margin: 0; font-weight: 600; } .pill { display: inline-block; border-radius: 999px; padding: 3px 8px; font-size: 12px; font-weight: 700; } .auto { background: oklch(0.3 .07 150); color: var(--good); } .escalate { background: oklch(0.32 .06 80); color: var(--warn); } .blocked, .error { background: oklch(.3 .07 25); color: oklch(.84 .11 25); }
    label { display: block; color: var(--muted); font-size: 13px; margin: 18px 0 6px; } input { width: 100%; padding: 10px 11px; border: 1px solid var(--line); border-radius: 8px; background: var(--canvas); color: var(--ink); font: inherit; } input:focus { border-color: var(--accent); outline: 2px solid oklch(.76 .15 190 / .25); }
    .approval { display: flex; align-items: start; gap: 8px; margin: 14px 0; color: var(--muted); font-size: 13px; } .approval input { width: auto; margin-top: 4px; } .notice { margin-top: 18px; min-height: 48px; padding: 12px; border-radius: 8px; background: oklch(.21 .02 248); color: var(--muted); } .notice strong { color: var(--ink); } code { color: var(--accent); } @media (max-width: 720px) { main { padding: 28px 16px; } header { display: block; } .status { margin-top: 12px; } .workspace { grid-template-columns: 1fr; } }
  </style>
</head>
<body><main>
  <header><div><h1>Travel Disruption Concierge</h1><p>Policy-gated rebooking with a Prava Sandbox payment handoff.</p></div><div class="status" id="health">Checking Prava Sandbox…</div></header>
  <div class="workspace"><section><h2>1. Simulate a disruption</h2><p>Generate a proposal to inspect how the orchestrator applies the policy boundary.</p><div class="choices"><button data-scenario="auto">$42 · auto approve</button><button data-scenario="escalate">$120 · member review</button><button data-scenario="blocked">$200 · blocked</button></div><div id="proposal" class="notice">Choose a scenario to begin.</div></section>
  <section><h2>2. Secure payment approval</h2><p>Prava opens in a separate secure page. This app never receives card data, a network token, or CVV.</p><div class="notice"><strong>Sandbox test card only</strong><br>Visa <code>4622 9431 2313 7789</code><br>Expiry <code>12/27</code> · CVV <code>757</code> · OTP <code>456789</code><br><small>Use this only on Prava Sandbox. Do not enter a real card.</small></div><label for="email">Member email</label><input id="email" type="email" placeholder="traveler@example.com" autocomplete="email"><label class="approval"><input id="approval" type="checkbox"> <span>I approve this escalated rebooking proposal.</span></label><button class="primary" id="pay" disabled>Continue to Prava Sandbox</button><div id="payment" class="notice">Generate an eligible proposal first.</div></section></div>
</main><script>
let proposal = null, poller = null;
const $ = (id) => document.getElementById(id);
async function request(url, options = {}) { const res = await fetch(url, options); const body = await res.json(); if (!res.ok) throw new Error(body.detail || 'Request failed'); return body; }
async function makeProposal(scenario) { clearInterval(poller); $('pay').disabled = true; $('payment').textContent = 'Generating policy decision…'; try { proposal = await request('/api/proposals/demo', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({scenario})}); const p = proposal.proposal, v = proposal.verdict; $('proposal').innerHTML = `<strong>${p.original_flight || 'AA202'} → ${p.candidate_flight}</strong><dl><dt>Fare delta</dt><dd>$${p.fare_delta_usd.toFixed(2)}</dd><dt>Policy result</dt><dd><span class="pill ${v.verdict}">${v.verdict.replace('_',' ')}</span></dd><dt>Rule</dt><dd>${v.policy_rule_id}</dd></dl>`; $('pay').disabled = v.verdict === 'blocked'; $('payment').innerHTML = v.verdict === 'blocked' ? '<span class="error">Blocked by policy. No payment session can be created.</span>' : 'Ready to create a Prava Sandbox session.'; } catch(e) { $('proposal').innerHTML = `<span class="error">${e.message}</span>`; } }
async function startPayment() { if (!proposal) return; $('pay').disabled = true; try { const session = await request(`/api/proposals/${proposal.proposal_id}/start-prava`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({member_email:$('email').value, member_approved:$('approval').checked})}); window.open(session.iframe_url, '_blank', 'noopener'); $('payment').innerHTML = `<strong>Prava session created.</strong> Complete the secure flow in the new tab; this page will check its status. Expires ${new Date(session.expires_at).toLocaleTimeString()}.`; poller = setInterval(async () => { try { const state = await request(`/api/prava/sessions/${session.session_id}`); if (state.status === 'completed') { clearInterval(poller); $('payment').innerHTML = '<strong>Prava approval complete.</strong> The one-time credential is held server-side for a future booking integration.'; } else if (state.status === 'failed') { clearInterval(poller); $('payment').innerHTML = '<span class="error">Prava reported a failed payment flow.</span>'; } } catch (_) {} }, 3000); } catch(e) { $('payment').innerHTML = `<span class="error">${e.message}</span>`; $('pay').disabled = false; } }
document.querySelectorAll('[data-scenario]').forEach(b => b.addEventListener('click', () => makeProposal(b.dataset.scenario))); $('pay').addEventListener('click', startPayment);
request('/api/health').then(x => $('health').textContent = x.prava_sandbox_reachable ? 'Prava Sandbox reachable' : 'Prava Sandbox unavailable').catch(() => $('health').textContent = 'Prava Sandbox check failed');
</script></body></html>'''
