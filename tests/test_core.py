import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
