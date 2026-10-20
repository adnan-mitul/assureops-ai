"""Groq provider (OpenAI-compatible API at https://api.groq.com/openai/v1).

Server-side only: the key comes from the deployment secret store
(`GROQ_API_KEY`), never from a browser or a request. Disabled unless
`GROQ_ENABLED=true`, a model is pinned (`GROQ_MODEL_F`), that exact model is
listed by the account's `/models`, it fits the project's model-size
constraint (or an operator recorded an explicit exception), and the phase has a
qualification record. Structured output is requested only for models known to
support JSON schema; every response is validated locally either way.
"""

import re

from .base import OpenAICompatible

# Models documented by Groq as supporting `response_format: json_schema`; others use JSON object mode.
STRUCTURED_OUTPUT_MODELS = {"openai/gpt-oss-20b", "openai/gpt-oss-120b", "moonshotai/kimi-k2-instruct", "moonshotai/kimi-k2-instruct-0905",
                            "meta-llama/llama-4-maverick-17b-128e-instruct", "meta-llama/llama-4-scout-17b-16e-instruct"}


class GroqProvider(OpenAICompatible):
    name = "groq"

    def json_mode(self, model: str) -> str:
        return "json_schema" if model in STRUCTURED_OUTPUT_MODELS else "json_object"

    def extra_body(self, model: str) -> dict:
        # Reasoning models: keep reasoning short and out of the response so the token budget goes to the JSON answer.
        if model.startswith("openai/gpt-oss"):
            return {"reasoning_effort": "low", "include_reasoning": False}
        return {}


    def screen(self, text: str, model: str) -> tuple[str, float | None]:
        """Prompt Guard models return the probability that the text is a jailbreak/injection attempt."""
        result = self._once(model, {"model": model, "messages": [{"role": "user", "content": text[:2000]}]}, expect_json=False)
        if not result.ok:
            return result.status, None
        try:
            return "succeeded", float(result.content.strip())
        except (TypeError, ValueError):
            return "invalid_output", None


def parameters_billion(model_id: str) -> float | None:
    """Best-effort size from the model ID (e.g. llama-3.1-8b-instant -> 8). Mixture-of-experts names count total experts' base."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*b(?![a-z])", model_id.lower())
    return float(match.group(1)) if match else None


def fits_constraint(model_id: str, max_billion: float) -> bool:
    size = parameters_billion(model_id)
    return size is not None and size <= max_billion
