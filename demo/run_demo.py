"""
Run: python demo/run_demo.py
No API keys required -- everything is mocked but structurally real,
so this is your fallback if a live API dies mid-demo.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agents.monitor import MonitorAgent
from app.agents.reasoning import ReasoningAgent
from app.agents.rebooking import RebookingAgent
from app.orchestrator import Orchestrator

if __name__ == "__main__":
    monitor = MonitorAgent()
    reasoning = ReasoningAgent()
    orchestrator = Orchestrator()
    rebooking = RebookingAgent()

    print("=== Monitor: detecting disruption ===")
    disruption = monitor.detect(pnr="PNR-DEMO-001")
    print(disruption.model_dump_json(indent=2))

    print("\n=== Reasoning: proposing alternative ===")
    proposal = reasoning.propose(disruption)
    print(proposal.model_dump_json(indent=2))

    print("\n=== Orchestrator: policy gate ===")
    verdict = orchestrator.gate(proposal)
    print(verdict.model_dump_json(indent=2))

    print("\n=== Rebooking: executing via Prava ===")
    result = rebooking.execute(proposal, verdict)
    print(json.dumps(result, indent=2))

    print("\n=== Audit trail (audit_log.jsonl) ===")
    with open(os.path.join(os.path.dirname(__file__), "..", "audit_log.jsonl")) as f:
        for line in f:
            print(line.strip())
