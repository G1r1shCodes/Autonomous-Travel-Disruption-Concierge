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

You should see Monitor → Reasoning → Orchestrator → Rebooking (via mocked
Prava) → audit trail, printed end to end.

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

3. **Wire up FastAPI** (`app/main.py` — not yet created) as a thin wrapper
   around the same agent objects used in `demo/run_demo.py`, so you have a
   live-looking dashboard/endpoint if you want one. Not required for the
   demo to work.

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
app/integrations/prava_client.py  <- REPLACE THIS with real Prava SDK
demo/run_demo.py             <- runs the whole pipeline, no keys needed
```

## If something breaks 1 hour before the deadline

Run `python demo/run_demo.py` — it has no external dependencies and will
always work. Screen-record it as your fallback demo video before you touch
anything live.
