"""Private inference on the hosting infrastructure.

Generation: any OpenAI-compatible server (llama.cpp server, vLLM, TGI with the
messages API) at `PRIVATE_INFERENCE_URL`, with one pinned model ID per phase.
Embedding and classification: text-embeddings-inference compatible endpoints
(`/embed`, `/predict`). Customer content never leaves this deployment on
these routes.
"""

import time

import httpx

from .base import OpenAICompatible, ProviderResult


class PrivateGeneration(OpenAICompatible):
    name = "private"
    max_tokens_field = "max_tokens"

    def json_mode(self, model: str) -> str:
        # Ollama/vLLM constrain decoding to the phase schema; small models need it to stay well-formed.
        return "json_schema"


class PrivateEncoder:
    """Embedding (`/embed`) and pair-classification (`/predict`) adapters."""

    name = "private"

    def __init__(self, base_url: str, *, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, body: dict, model: str) -> ProviderResult:
        started = time.perf_counter()
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout, trust_env=False) as http:
                res = http.post(path, json=body)
        except httpx.TimeoutException:
            return ProviderResult("timeout", self.name, model, error="encoder timed out")
        except httpx.HTTPError as exc:
            return ProviderResult("unavailable", self.name, model, error=f"transport error: {exc.__class__.__name__}")
        latency = round((time.perf_counter() - started) * 1000)
        if res.status_code != 200:
            return ProviderResult("unavailable", self.name, model, latency_ms=latency, error=f"HTTP {res.status_code}")
        return ProviderResult("succeeded", self.name, model, parsed={"result": res.json()}, latency_ms=latency)

    BATCH = 32  # the encoder service accepts at most 32 inputs per request

    def _batched(self, path: str, inputs: list, model: str, extra: dict) -> ProviderResult:
        """Split into service-sized requests; any failed batch fails the whole call (never a partial result)."""
        results, latency = [], 0
        for i in range(0, len(inputs), self.BATCH):
            part = self._post(path, {"model": model, "inputs": inputs[i:i + self.BATCH], **extra}, model)
            if not part.ok:
                return part
            results.extend(part.parsed["result"])
            latency += part.latency_ms or 0
        return ProviderResult("succeeded", self.name, model, parsed={"result": results}, latency_ms=latency)

    def embed(self, texts: list[str], model: str) -> ProviderResult:
        return self._batched("/embed", texts, model, {"truncate": True})

    def classify_pairs(self, pairs: list[tuple[str, str]], model: str) -> ProviderResult:
        return self._batched("/predict", [list(p) for p in pairs], model, {"raw_scores": False})
