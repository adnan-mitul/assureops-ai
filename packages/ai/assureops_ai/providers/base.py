"""Provider contract and an OpenAI-compatible chat client shared by Groq and private serving.

Every failure is a typed status (never an exception that a caller could read
as success): auth_failed, model_unavailable, rate_limited, timeout,
unavailable, refused, invalid_output. Keys are sent only in the Authorization
header and never logged or returned.
"""

import json
import time
from dataclasses import dataclass, field

import httpx

RETRYABLE = {"rate_limited", "timeout", "unavailable"}


@dataclass
class ProviderResult:
    status: str
    provider: str
    model: str
    content: str | None = None
    parsed: dict | None = None
    usage: dict = field(default_factory=dict)
    request_id: str | None = None
    latency_ms: int | None = None
    error: str | None = None
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"


class OpenAICompatible:
    name = "openai-compatible"
    max_tokens_field = "max_completion_tokens"

    def __init__(self, base_url: str, api_key: str | None, *, timeout: float = 20.0, max_retries: int = 2,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self._transport = transport

    def _client(self) -> httpx.Client:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        return httpx.Client(base_url=self.base_url, headers=headers, timeout=self.timeout, trust_env=False,
                            follow_redirects=False, transport=self._transport)

    def extra_body(self, model: str) -> dict:
        """Provider/model-specific request fields (none by default)."""
        return {}

    def list_models(self) -> tuple[str, list[dict]]:
        """(status, models). Models carry `id` and whatever metadata the provider returns."""
        try:
            with self._client() as http:
                res = http.get("/models")
        except httpx.TimeoutException:
            return "timeout", []
        except httpx.HTTPError:
            return "unavailable", []
        status = self._status_for(res)
        if status != "succeeded":
            return status, []
        return "succeeded", [m for m in res.json().get("data", []) if isinstance(m, dict) and m.get("id")]

    @staticmethod
    def _status_for(res: httpx.Response) -> str:
        if res.status_code in (401, 403):
            return "auth_failed"
        if res.status_code == 404:
            return "model_unavailable"
        if res.status_code == 429:
            return "rate_limited"
        if res.status_code >= 500:
            return "unavailable"
        if res.status_code >= 400:
            return "invalid_request"
        return "succeeded"

    def generate(self, *, model: str, system: str, user: str, max_tokens: int, json_mode: str = "json_object",
                 schema: dict | None = None) -> ProviderResult:
        body = {"model": model, "temperature": 0, self.max_tokens_field: max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode == "json_schema" and schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "phase_output", "schema": schema, "strict": False}}
        elif json_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        body.update(self.extra_body(model))
        attempt, last = 0, None
        while attempt <= self.max_retries:
            attempt += 1
            last = self._once(model, body)
            last.attempts = attempt
            if last.status not in RETRYABLE or attempt > self.max_retries:
                return last
            time.sleep(min(2 ** attempt, 8))
        return last

    def _once(self, model: str, body: dict, expect_json: bool = True) -> ProviderResult:
        started = time.perf_counter()
        try:
            with self._client() as http:
                res = http.post("/chat/completions", json=body)
        except httpx.TimeoutException:
            return ProviderResult("timeout", self.name, model, error="provider request timed out")
        except httpx.HTTPError as exc:
            return ProviderResult("unavailable", self.name, model, error=f"transport error: {exc.__class__.__name__}")
        latency = round((time.perf_counter() - started) * 1000)
        request_id = res.headers.get("x-request-id")
        status = self._status_for(res)
        if status != "succeeded":
            message = ""
            try:
                message = str(res.json().get("error", {}).get("message", ""))[:300]
            except ValueError:
                pass
            return ProviderResult(status, self.name, model, request_id=request_id, latency_ms=latency, error=f"HTTP {res.status_code}: {message}")
        try:
            data = res.json()
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
            usage = {k: data.get("usage", {}).get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
            request_id = data.get("id") or request_id
        except (ValueError, KeyError, IndexError, TypeError):
            return ProviderResult("invalid_output", self.name, model, request_id=request_id, latency_ms=latency, error="unexpected response shape")
        if choice.get("finish_reason") == "content_filter" or choice["message"].get("refusal"):
            return ProviderResult("refused", self.name, model, usage=usage, request_id=request_id, latency_ms=latency, error="provider refused")
        if not expect_json:
            return ProviderResult("succeeded", self.name, model, content=content, usage=usage, request_id=request_id, latency_ms=latency)
        if choice.get("finish_reason") == "length":
            return ProviderResult("invalid_output", self.name, model, content=content, usage=usage, request_id=request_id, latency_ms=latency,
                                  error="output truncated at the token budget")
        try:
            parsed = json.loads(content)
        except ValueError:
            return ProviderResult("invalid_output", self.name, model, content=content, usage=usage, request_id=request_id, latency_ms=latency,
                                  error="output is not JSON")
        if not isinstance(parsed, dict):
            return ProviderResult("invalid_output", self.name, model, content=content, usage=usage, request_id=request_id, latency_ms=latency,
                                  error="output is not a JSON object")
        return ProviderResult("succeeded", self.name, model, content=content, parsed=parsed, usage=usage, request_id=request_id, latency_ms=latency)
