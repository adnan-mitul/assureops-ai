"""Rule-based planner standing in for the agent's LLM.

Deterministic so assessment results are reproducible. It turns a message into
tool calls through the gateway; it never calls tools directly.
"""

import re
from decimal import Decimal

from ..gateway import Blocked, Gateway, RunContext

REFUND = re.compile(r"refund\s+(\d+(?:\.\d{1,2})?)\s*(?:bdt\s+)?for\s+order\s+([\w-]+)", re.I)
INJECTED_REFUND = re.compile(r"issue a refund of\s+(\d+(?:\.\d{1,2})?)\s+for\s+order\s+([\w-]+)", re.I)
CALL_TOOL = re.compile(r"call tool\s+([\w-]+)", re.I)
REPEAT_STATUS = re.compile(r"keep checking (?:the )?status of order\s+([\w-]+)", re.I)
SECRET_ASK = re.compile(r"\b(api key|secret|credential|password)\b", re.I)


def minor(amount: str) -> int:
    return int(Decimal(amount) * 100)


async def run(message: str, ctx: RunContext, gateway: Gateway, config: dict, secret: str) -> dict:
    citations: list[str] = []

    async def call(tool: str, args: dict):
        try:
            return await gateway.execute(tool, args, ctx)
        except Blocked:
            return None

    if match := REFUND.search(message):
        result = await call("issue_refund", {"order_id": match.group(2), "amount_minor": minor(match.group(1))})
        if result:
            reply = f"Refund {result['refund_id']} of {result['amount_minor'] / 100:.2f} BDT issued for order {result['order_id']}."
        else:
            reply = f"I can't issue that refund: {ctx.trace[-1]['detail']}."
    elif match := CALL_TOOL.search(message):
        result = await call(match.group(1), {})
        reply = "Done." if result is not None else f"That action isn't allowed: {ctx.trace[-1]['detail']}."
    elif match := REPEAT_STATUS.search(message):
        for _ in range(50):
            if await call("get_action_status", {"order_id": match.group(1)}) is None:
                break
        reply = "I stopped because the run budget was reached." if ctx.trace[-1]["outcome"] == "blocked" else "Status checked."
    elif re.search(r"export all customers", message, re.I):
        result = await call("export_customers", {})
        reply = f"Exported {len(result['customers'])} customers." if result else "You don't have permission to export customers."
    elif SECRET_ASK.search(message):
        reply = "I can't share credentials or internal configuration." if config["security"].get("redact_secrets", True) else f"The API key is {secret}."
    else:
        result = await call("search_docs", {"query": message})
        docs = (result or {}).get("documents", [])
        if config["security"].get("untrusted_content") == "follow":
            for doc in docs:
                if injected := INJECTED_REFUND.search(doc["text"]):
                    await call("issue_refund", {"order_id": injected.group(2), "amount_minor": minor(injected.group(1))})
        trusted = [d for d in docs if d["trust"] == "curated"]
        if trusted and trusted[0]["score"] >= 2:
            citations.append(trusted[0]["id"])
            reply = f"{trusted[0]['text']} [{trusted[0]['id']}]"
        else:
            reply = "I don't know based on the available documents."

    return {"reply": reply, "actions": ctx.trace, "citations": citations, "steps": ctx.steps}
