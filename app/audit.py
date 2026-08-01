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


def _sanitize_detail(value):
    """Tokenize PNRs before audit persistence; retain only safe event metadata."""
    if isinstance(value, dict):
        return {
            key: (
                f"pnr_{hashlib.sha256(str(item).encode()).hexdigest()[:12]}"
                if key.lower() == "pnr"
                else _sanitize_detail(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_detail(item) for item in value]
    return value


def verify_chain() -> bool:
    """Verify the append-only hash chain in the local MVP audit log."""
    if not AUDIT_LOG.exists():
        return True
    previous_hash = "genesis"
    for line in AUDIT_LOG.read_text().strip().splitlines():
        entry = json.loads(line)
        immutable_hash = entry.pop("immutable_hash", None)
        if entry.get("prev_hash") != previous_hash:
            return False
        calculated = f"sha256:{hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()[:16]}..."
        if immutable_hash != calculated:
            return False
        previous_hash = immutable_hash
    return True


def log_event(agent: str, sub_component: str, action: str, detail: dict, policy_verdict: str = None):
    prev_hash = _last_hash()
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": agent,
        "sub_component": sub_component,
        "action": action,
        "detail": _sanitize_detail(detail),
        "policy_verdict": policy_verdict,
        "prev_hash": prev_hash,
    }
    entry_hash = hashlib.sha256((json.dumps(entry, sort_keys=True)).encode()).hexdigest()
    entry["immutable_hash"] = f"sha256:{entry_hash[:16]}..."
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry
