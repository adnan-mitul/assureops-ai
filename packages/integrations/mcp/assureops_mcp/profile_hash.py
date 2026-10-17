import hashlib
import json


def canonical_hash(value) -> str:
    """Same canonical JSON hash AssureOps uses, so schema hashes match across services."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
