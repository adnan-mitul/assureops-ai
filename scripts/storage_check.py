"""Evidence store round trip: put, read back, verify the hash, delete. Exits non-zero on any failure.

    python scripts/storage_check.py

Run after the object store starts (CI does) so a store that cannot grow its volumes or
answer in time fails fast with a clear message instead of as timed-out assessment steps.
"""

import hashlib
import secrets
import sys
import time

from assureops_domain import evidence_store


def main():
    store = evidence_store.storage()
    key = f"_storage_check/{secrets.token_hex(8)}"
    data = secrets.token_bytes(2048)
    for attempt in range(1, 6):
        started = time.time()
        try:
            store.put(key, data)
            back = store.get(key)
            store.delete(key)
        except Exception as exc:  # report and retry: a fresh store may still be allocating its first volume
            print(f"attempt {attempt}: {store.name} store error {exc.__class__.__name__}: {exc}")
            time.sleep(3 * attempt)
            continue
        ok = back is not None and hashlib.sha256(back).digest() == hashlib.sha256(data).digest()
        print(f"{store.name} store round trip {'ok' if ok else 'MISMATCH'} in {time.time() - started:.2f} s")
        return 0 if ok else 1
    print("evidence store is not usable")
    return 1


if __name__ == "__main__":
    sys.exit(main())
