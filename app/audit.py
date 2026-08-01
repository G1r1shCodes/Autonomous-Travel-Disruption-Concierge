"""
Append-only, hash-chained audit trail.
For the hackathon this writes to a local JSONL file. Swap `_write` for a
Postgres INSERT when you have time -- the schema doesn't need to change.
"""
import hashlib
import json
import time
from pathlib import Path

AUDIT_LOG = Path(__file__).parent.parent / "audit_log.jsonl"


def _last_hash() -> str:
    if not AUDIT_LOG.exists():
        return "genesis"
    lines = AUDIT_LOG.read_text().strip().splitlines()
    if not lines:
        return "genesis"
    return json.loads(lines[-1])["immutable_hash"]


def log_event(agent: str, sub_component: str, action: str, detail: dict, policy_verdict: str = None):
    prev_hash = _last_hash()
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": agent,
        "sub_component": sub_component,
        "action": action,
        "detail": detail,
        "policy_verdict": policy_verdict,
        "prev_hash": prev_hash,
    }
    entry_hash = hashlib.sha256((json.dumps(entry, sort_keys=True)).encode()).hexdigest()
    entry["immutable_hash"] = f"sha256:{entry_hash[:16]}..."
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry
