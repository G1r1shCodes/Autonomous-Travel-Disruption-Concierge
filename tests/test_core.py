import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from app.agents.monitor import MonitorAgent
from app.agents.rebooking import RebookingAgent
from app.audit import chain_status, log_event, verify_chain
from app.models import RebookingProposal
from app.orchestrator import Orchestrator


class CoreFlowTests(unittest.TestCase):
    def test_policy_branches(self):
        gate = Orchestrator()
        base = dict(disruption_id="d1", candidate_flight="AA318", cabin_class_same=True)
        self.assertEqual(gate.gate(RebookingProposal(**base, fare_delta_usd=42)).verdict, "auto_approve")
        self.assertEqual(gate.gate(RebookingProposal(**base, fare_delta_usd=120)).verdict, "escalate")
        self.assertEqual(gate.gate(RebookingProposal(**base, fare_delta_usd=200)).verdict, "blocked")

    def test_mock_rebooking_completes(self):
        proposal = RebookingProposal(disruption_id="d1", candidate_flight="AA318", fare_delta_usd=42, cabin_class_same=True)
        verdict = Orchestrator().gate(proposal)
        with patch.dict("os.environ", {"PRAVA_MODE": "mock"}):
            result = RebookingAgent().execute(proposal, verdict)
        self.assertEqual(result["status"], "booked")

    def test_audit_chain_round_trip(self):
        import app.audit as audit
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "audit.jsonl"
            lock = Path(directory) / "audit.lock"
            with patch.object(audit, "AUDIT_LOG", log), patch.object(audit, "AUDIT_LOCK", lock):
                log_event("test", "unit", "write", {"pnr": "secret-pnr"})
                self.assertTrue(verify_chain())
                self.assertTrue(chain_status()["valid"])
                self.assertEqual(chain_status()["entries"], 1)
                self.assertNotIn("secret-pnr", log.read_text())


    def test_comms_escalated_carries_decision_links(self):
        from app.agents.comms import CommsAgent
        from app.agents.monitor import MonitorAgent

        # Never fire a real Twilio message from a unit test.
        with ExitStack() as stack:
            stack.enter_context(patch("app.agents.comms.CommsAgent._send_whatsapp", return_value=False))
            stack.enter_context(patch("app.agents.comms.CommsAgent._send_sms", return_value=False))
            disruption = MonitorAgent().detect(pnr="PNR-DEMO-002")
            notification = CommsAgent().notify(
                disruption,
                {"status": "awaiting_member_approval", "flight": "DL551"},
                {},
                proposal_id="prop_1",
                public_base_url="https://demo.ngrok-free.app",
            )
        whatsapp = notification["channels"]["whatsapp"]
        self.assertTrue(any(a.get("url") for a in whatsapp["actions"]))
        self.assertIn("action=approve", whatsapp["body"])
        self.assertIn("action=decline", whatsapp["body"])

    def test_comms_auto_has_no_actions(self):
        from app.agents.comms import CommsAgent
        from app.agents.monitor import MonitorAgent

        disruption = MonitorAgent().detect(pnr="PNR-DEMO-001")
        notification = CommsAgent().notify(
            disruption,
            {"status": "booked", "flight": "AA318"},
            {},
        )
        self.assertEqual(notification["channels"]["whatsapp"]["actions"], [])

    def test_comms_webhook_approve_is_idempotent(self):
        from fastapi.testclient import TestClient
        import app.main as main

        # Never hit real OpenAI or Twilio from tests.
        no_external = [
            patch("app.agents.reasoning.ReasoningAgent._choose_with_openai", return_value=None),
            patch("app.agents.comms.CommsAgent._send_whatsapp", return_value=False),
            patch("app.agents.comms.CommsAgent._send_sms", return_value=False),
        ]
        with ExitStack() as stack:
            for p in no_external:
                stack.enter_context(p)
            client = TestClient(main.app)
            resp = client.post("/api/proposals/demo", json={"scenario": "escalate"})
        self.assertEqual(resp.status_code, 200)
        proposal_id = resp.json()["proposal_id"]

        page = client.get(f"/api/comms/decision?proposal_id={proposal_id}&action=approve")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Rebooking approved", page.text)
        self.assertEqual(main._proposals[proposal_id]["decision"], "approve")

        # A second (or conflicting) tap must not flip or re-log the decision.
        client.get(f"/api/comms/decision?proposal_id={proposal_id}&action=decline")
        self.assertEqual(main._proposals[proposal_id]["decision"], "approve")

    def test_comms_webhook_rejects_unknown_and_non_escalated(self):
        from fastapi.testclient import TestClient
        import app.main as main

        no_external = [
            patch("app.agents.reasoning.ReasoningAgent._choose_with_openai", return_value=None),
            patch("app.agents.comms.CommsAgent._send_whatsapp", return_value=False),
            patch("app.agents.comms.CommsAgent._send_sms", return_value=False),
        ]
        with ExitStack() as stack:
            for p in no_external:
                stack.enter_context(p)
            client = TestClient(main.app)
            missing = client.get("/api/comms/decision?proposal_id=does-not-exist&action=approve")
            self.assertIn("not recorded", missing.text)

            resp = client.post("/api/proposals/demo", json={"scenario": "auto"})
            proposal_id = resp.json()["proposal_id"]
            page = client.get(f"/api/comms/decision?proposal_id={proposal_id}&action=approve")
            self.assertIn("not recorded", page.text)
            self.assertIsNone(main._proposals[proposal_id].get("decision"))


if __name__ == "__main__":
    unittest.main()
