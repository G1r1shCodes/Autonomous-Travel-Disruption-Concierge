"""
Append-only, hash-chained audit trail.
For the hackathon this writes to a local JSONL file. Swap `_write` for a
Postgres INSERT when you have time -- the schema doesn't need to change.
"""
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
AUDIT_LOG = DATA_DIR / "audit_log.jsonl"
AUDIT_LOCK = AUDIT_LOG.with_suffix(".lock")


@contextmanager
def _append_lock():
    """Serialize append operations across threads and worker processes."""
    lock_file = open(AUDIT_LOCK, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            # `msvcrt.locking` locks an existing byte range. Seed the lock
            # file once so the first writer can acquire byte zero reliably.
            if os.path.getsize(AUDIT_LOCK) == 0:
                lock_file.write("0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


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
    try:
        lines = AUDIT_LOG.read_text().strip().splitlines()
        for line in lines:
            entry = json.loads(line)
            immutable_hash = entry.get("immutable_hash")
            body = {key: value for key, value in entry.items() if key != "immutable_hash"}
            if body.get("prev_hash") != previous_hash:
                return False
            calculated = f"sha256:{hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]}..."
            if immutable_hash != calculated:
                return False
            previous_hash = immutable_hash
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    return True


def chain_status() -> dict[str, object]:
    """Return a small diagnostic suitable for the dashboard and health checks."""
    if not AUDIT_LOG.exists():
        return {"valid": True, "entries": 0, "last_hash": "genesis"}
    try:
        lines = [line for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
        last_hash = json.loads(lines[-1]).get("immutable_hash", "unknown") if lines else "genesis"
    except (OSError, json.JSONDecodeError):
        return {"valid": False, "entries": 0, "last_hash": "unknown"}
    return {"valid": verify_chain(), "entries": len(lines), "last_hash": last_hash}


def recent_entries(limit: int = 50) -> list[dict]:
    """Return the most recent audit entries for the dashboard viewer."""
    if not AUDIT_LOG.exists():
        return []
    try:
        lines = [line for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
        entries = [json.loads(line) for line in lines[-limit:]]
        entries.reverse()  # newest first
        return entries
    except (OSError, json.JSONDecodeError):
        return []


def log_event(
    agent: str,
    sub_component: str,
    action: str,
    detail: dict,
    policy_verdict: str = None,
    disruption_id: str = None,
):
    """Append an immutable, hash-chained event to the audit trail.

    Each entry carries an ``event_id``, per-agent attribution, and a
    ``disruption_id`` link so that all events for a single disruption can
    be traced together — matching the sample audit entry in §5.3 of the
    pitch document.
    """
    # Read the tail, calculate the hash, and append while holding the same
    # lock. Without this, concurrent agent workers can create a forked chain.
    with _append_lock():
        prev_hash = _last_hash()
        entry = {
            "event_id": f"evt_{uuid4().hex[:8]}",
            "disruption_id": disruption_id,
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
        with open(AUDIT_LOG, "a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(entry) + "\n")
            audit_file.flush()
            os.fsync(audit_file.fileno())
        return entry
