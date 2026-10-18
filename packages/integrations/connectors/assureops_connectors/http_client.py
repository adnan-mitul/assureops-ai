"""Bounded HTTP client pinned to one connection origin.

No redirects, no proxy/environment configuration, capped response size and
time, credentials attached per request from the actor map and never written
into evidence.
"""

import json
import secrets
import time

import httpx

from .egress import EgressDenied, check_path

MAX_RESPONSE_BYTES = 512_000
EVIDENCE_BODY_CHARS = 6_000
BLOCKED_HEADERS = {"host", "authorization", "cookie", "content-length", "transfer-encoding", "connection"}


class TargetError(Exception):
    """Transport or protocol failure: not evidence of an application defect."""


class Actors:
    """Maps logical actor names to credentials. `anonymous` sends none; `invalid` sends a random bogus value."""

    def __init__(self, auth: dict, credentials: dict[str, str]):
        self.auth = auth or {"type": "bearer", "header": "Authorization", "prefix": "Bearer "}
        self.credentials = credentials

    def names(self) -> set[str]:
        return set(self.credentials) | {"anonymous", "invalid"}

    def headers(self, actor: str | None) -> dict:
        if actor in (None, "anonymous"):
            return {}
        if actor == "invalid":
            value = "invalid-" + secrets.token_hex(12)
        elif actor in self.credentials:
            value = self.credentials[actor]
        else:
            raise EgressDenied(f"actor {actor!r} has no credential in this connection")
        kind = self.auth.get("type", "bearer")
        if kind == "bearer":
            return {self.auth.get("header", "Authorization"): self.auth.get("prefix", "Bearer ") + value}
        if kind == "header":
            return {self.auth["header"]: value}
        raise EgressDenied(f"unsupported auth type {kind}")


class TargetClient:
    def __init__(self, origin: str, scope: dict, actors: Actors, *, marker_header: str | None = None, marker_value: str | None = None,
                 timeout: float = 15.0):
        self.origin = origin
        self.scope = scope
        self.actors = actors
        self.base_headers = {"Accept": "application/json", "User-Agent": "AssureOps-Runner/1.0"}
        if marker_header and marker_value:
            self.base_headers[marker_header] = marker_value
        self.http = httpx.Client(base_url=origin, follow_redirects=False, trust_env=False, timeout=timeout,
                                 limits=httpx.Limits(max_connections=8))
        self.requests_made = 0

    def close(self):
        self.http.close()

    def request(self, method: str, path: str, *, actor: str | None = None, body=None, headers: dict | None = None,
                enforce_scope: bool = True) -> dict:
        if enforce_scope:
            check_path(path, self.scope.get("allowed_paths", []), method, self.scope.get("allowed_methods", ["GET", "POST"]))
        limit = int(self.scope.get("max_requests_per_test", 60))
        if self.requests_made >= limit:
            raise EgressDenied(f"request budget of {limit} per test exhausted")
        self.requests_made += 1
        extra = {k: v for k, v in (headers or {}).items() if k.lower() not in BLOCKED_HEADERS}
        sent_headers = {**self.base_headers, **extra, **self.actors.headers(actor)}
        started = time.perf_counter()
        try:
            with self.http.stream(method.upper(), path, json=body if body is not None else None, headers=sent_headers) as response:
                raw = b""
                for chunk in response.iter_bytes():
                    raw += chunk
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise TargetError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
                status = response.status_code
                content_type = response.headers.get("content-type", "")
                location = response.headers.get("location")
        except httpx.TimeoutException as exc:
            raise TargetError(f"timeout: {exc.__class__.__name__}")
        except httpx.HTTPError as exc:
            raise TargetError(f"transport error: {exc.__class__.__name__}")
        elapsed = round((time.perf_counter() - started) * 1000)
        text = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            parsed = text
        return {"status": status, "body": parsed, "content_type": content_type, "elapsed_ms": elapsed,
                "redirect_not_followed": location if 300 <= status < 400 else None}


def evidence_view(result: dict) -> dict:
    """What is stored as evidence: status, bounded body, timing. Never request credentials."""
    body = result.get("body")
    text = json.dumps(body, sort_keys=True) if not isinstance(body, str) else body
    stored = body if len(text) <= EVIDENCE_BODY_CHARS else text[:EVIDENCE_BODY_CHARS] + "...[truncated]"
    out = {"status": result.get("status"), "body": stored, "elapsed_ms": result.get("elapsed_ms")}
    if result.get("redirect_not_followed"):
        out["redirect_not_followed"] = result["redirect_not_followed"]
    return out
