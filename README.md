# Autonomous Travel-Disruption Concierge — Starter Scaffold

Everything here **runs end-to-end right now with zero API keys**, using mocked
integrations that match the real shape of Amadeus/Prava/Twilio calls. This is
so you always have a working fallback demo, and so you're editing real code
instead of starting from a blank folder.

## Quickstart

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python demo/run_demo.py
```

You should see Monitor → Reasoning → Orchestrator → a secure-payment
handoff requirement → audit trail, printed end to end. Use the dashboard
below to begin a real Prava Sandbox payment session.

The demo runs on any platform with no extra setup — it reconfigures its own
output to UTF-8, so the banner and emoji render correctly even in Windows
consoles (no `PYTHONIOENCODING` or other encoding workarounds needed).

## What to do next, in priority order

1. **Swap `app/integrations/prava_client.py` for the real Prava SDK.**
   This is the highest-judged part of the submission (VIC track sponsor).
   Don't hand-write the API calls — point Claude Code at
   https://github.com/Prava-Payments/prava-skills and ask it to integrate
   Prava payments into this file. Test the mandate/passkey flow live at
   https://playground.prava.space/ first so you know what you're wiring up.
   Get API keys at https://dashboard.prava.space/.

2. **Leave Amadeus mocked** (`app/agents/reasoning.py`) unless you have spare
   time — self-service signup is decommissioned, and it's not what's being
   judged. The mock candidate list is enough for a believable demo.

3. **Use the FastAPI dashboard** (`app/main.py`) as a thin wrapper around the
   same agent objects used in `demo/run_demo.py`. It exposes health checks,
   synthetic auto/escalate/blocked proposals, and a server-side Prava session
   handoff without exposing payment credentials to the browser.

4. **Comms Agent (WhatsApp)** — reuse your existing Twilio + FastAPI webhook
   code from your task-reminder project instead of writing this from
   scratch. It's the same pattern: inbound webhook, outbound template
   message, approve/decline buttons.

5. **Everything else in the pitch doc** (Benefits Agent, multi-region,
   PostgreSQL, Redis, Learning Flywheel) — keep these as "designed, not
   built" in your README/slides. Judges score the idea + a working core,
   not every box in the architecture diagram.

## File map

```
policy/policy.yaml          <- the actual trust boundary, human-readable
app/models.py                <- shared data shapes
app/orchestrator.py          <- policy gate, single choke point
app/audit.py                 <- hash-chained audit log (JSONL for now)
app/agents/monitor.py        <- detection (mocked)
app/agents/reasoning.py      <- scoring/candidate selection (mocked)
app/agents/rebooking.py      <- execution, calls Prava
app/agents/benefits.py       <- proposes/submits eligible benefit claims (mocked)
app/agents/comms.py          <- queues the member-facing update (mocked)
app/integrations/prava_client.py  <- REPLACE THIS with real Prava SDK
demo/run_demo.py             <- runs the whole pipeline, no keys needed
```

## If something breaks 1 hour before the deadline

Run `python demo/run_demo.py` — it has no external dependencies, needs no API
keys, and will always work on any OS (Windows included, no encoding flags
required). Screen-record it as your fallback demo video before you touch
anything live.

## Prava Sandbox dashboard

Copy `.env.example` to `.env`, add a sandbox `sk_test_...` key as
`PRAVA_SECRET_KEY` (the older `PRAVA_API_KEY` name is also supported), then
run:

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. The dashboard generates auto-approved,
member-review, and blocked policy examples. For eligible proposals it creates
a real Prava Sandbox `full_checkout` session server-side, opens Prava's secure checkout in a
new tab, and polls its status without exposing card data, the Visa network
token, or dynamic CVV to the browser. Airline booking remains mocked until an
actual booking-merchant integration consumes the one-time credential.

Each generated proposal also runs the mock Benefits and Comms agents: eligible
trip-delay claims are policy-gated and submitted, then a dashboard notification
is queued. This makes the five-agent orchestration demoable even if the
external payment passkey is temporarily unavailable.

The local `data/audit_log.jsonl` is append-only and hash-chained for the MVP.
The writer uses a cross-process lock so concurrent agent workers cannot fork
the chain. Existing logs created before that lock was added may report
`INVALID` if they contain a historical concurrent-write fork; delete
`data/audit_log.jsonl` (and its `.lock`) to start with a fresh log for a clean
demo run.

For the real hosted passkey test, expose the local dashboard through HTTPS and
set that public callback in `.env` before creating a session. With ngrok:

```bash
ngrok http 8000
```

Copy ngrok's `https://...` forwarding URL into
`PRAVA_CALLBACK_URL=https://.../prava/callback`, restart Uvicorn, and open the
same HTTPS ngrok URL in your browser. Never use a local `http://` callback for
the Prava-hosted passkey test.
