"""AssureOps deterministic enforcement gateway (plan §10, §12).

Sits between the agent's planner and the MCP tool server. Validates actor role,
tool registration, live tool schema, run budget, approval and action identity
before dispatch. Unavailable authorization means deny or hold, never allow.
No model is on this path.
"""

import uuid
from dataclasses import dataclass, field

import httpx

from . import mcp_client, settings
from .mcp_client import ToolError


class Blocked(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class RunContext:
    workspace: str
    requester: str
    role: str
    approval_id: str | None
    idempotency_key: str | None
    max_steps: int
    test_traffic: bool
    assessment_step_id: str | None = None
    steps: int = 0
    trace: list = field(default_factory=list)


def _schema_check(schema: dict, args: dict):
    props = schema.get("properties", {})
    unknown = set(args) - set(props)
    if unknown:
        raise Blocked("invalid_arguments", f"unknown fields {sorted(unknown)}")
    for name in schema.get("required", []):
        if name not in args:
            raise Blocked("invalid_arguments", f"missing {name}")
    for name, value in args.items():
        kinds = props[name].get("type") or [s.get("type") for s in props[name].get("anyOf", [])]
        kinds = kinds if isinstance(kinds, list) else [kinds]
        ok = any(
            (k == "string" and isinstance(value, str)) or (k == "integer" and isinstance(value, int) and not isinstance(value, bool))
            or (k == "null" and value is None) or k is None
            for k in kinds
        )
        if not ok:
            raise Blocked("invalid_arguments", f"{name} has the wrong type")


class Gateway:
    def __init__(self, config: dict, release: str, live_tools: dict, emitter, gateway_token: str):
        self.config = config
        self.release = release
        self.live_tools = live_tools
        self.emitter = emitter
        self.token = gateway_token

    def _api(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return httpx.request(method, f"{settings.API_URL}{path}", headers={"Authorization": f"Bearer {self.token}"}, timeout=5, **kwargs)
        except httpx.HTTPError as exc:
            raise Blocked("authorization_unavailable", f"enforcement ledger unreachable ({exc.__class__.__name__}); action held")

    async def execute(self, tool: str, args: dict, ctx: RunContext) -> dict:
        try:
            result = await self._execute(tool, args, ctx)
            self._record(ctx, tool, args, "executed", result=result)
            return result
        except Blocked as blocked:
            self._record(ctx, tool, args, "blocked", reason=blocked.reason, detail=blocked.detail)
            raise

    def _record(self, ctx: RunContext, tool: str, args: dict, outcome: str, **extra):
        entry = {"tool": tool, "args": args, "outcome": outcome, **extra}
        ctx.trace.append(entry)
        result = extra.get("result") or {}
        self.emitter.emit("tool_call", {
            "tool": tool, "outcome": outcome, "reason": extra.get("reason"),
            "action_id": result.get("action_id"), "approval_id": result.get("approval_id"),
            "side_effect": tool == "issue_refund", "requester_role": ctx.role,
        }, test_traffic=ctx.test_traffic)

    async def _execute(self, tool: str, args: dict, ctx: RunContext) -> dict:
        ctx.steps += 1
        if ctx.steps > ctx.max_steps:
            raise Blocked("budget_exhausted", f"run budget of {ctx.max_steps} steps reached")
        if tool not in self.config["tool_allowlist"]["allowed"] or tool not in self.live_tools:
            raise Blocked("unknown_tool", f"{tool} is not a reviewed, registered tool")
        rule = self.config["permission_policy"]["tools"].get(tool)
        if rule is None or ctx.role not in rule.get("roles", []):
            raise Blocked("forbidden_role", f"role {ctx.role} may not call {tool}")

        if tool == "search_docs":
            args = {**args, "workspace": ctx.workspace}  # workspace comes from the caller's identity, never the prompt
        _schema_check(self.live_tools[tool]["input_schema"], args if tool != "issue_refund" else {**args, "action_id": "x"})

        if tool != "issue_refund":
            try:
                return await mcp_client.call_tool(tool, args)
            except ToolError as exc:
                raise Blocked("tool_error", str(exc))
        return await self._issue_refund(args, ctx, rule)

    async def _issue_refund(self, args: dict, ctx: RunContext, rule: dict) -> dict:
        amount = args["amount_minor"]
        if amount <= 0:
            raise Blocked("invalid_arguments", "amount must be positive")
        if amount > rule["max_amount_minor"]:
            raise Blocked("limit_exceeded", f"amount above the {rule['max_amount_minor'] / 100:.2f} policy maximum")
        approval_required = amount > rule["approval_required_above_minor"]
        action_id = ctx.idempotency_key or f"act-{uuid.uuid4().hex}"
        body = {
            "action_id": action_id, "approval_id": ctx.approval_id if approval_required else None,
            "approval_required": approval_required, "tool": "issue_refund",
            "payload": {"order_id": args["order_id"], "amount_minor": amount},
            "tool_schema_hash": self.config["tool_schema_hashes"]["issue_refund"],
            "permission_policy_version": self.config["permission_policy"]["version"],
            "release": self.release, "requester": ctx.requester,
            "assessment_step_id": ctx.assessment_step_id,
        }
        if approval_required and not ctx.approval_id:
            raise Blocked("approval_required", "a manager approval is required for this amount")
        reserved = self._api("POST", "/v1/integration/actions/reserve", json=body)
        if reserved.status_code != 200:
            detail = reserved.json().get("detail", {})
            raise Blocked(detail.get("code", "approval_invalid") if isinstance(detail, dict) else "approval_invalid",
                          detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail))
        action = reserved.json()
        if action["state"] == "succeeded":
            return {**action["result"], "replayed": True}
        if action["state"] == "outcome_unknown":
            return await self._reconcile(action_id)
        if action["state"] in ("failed_definitive",):
            raise Blocked("action_failed", "this action already failed definitively")

        self._transition(action_id, "dispatching")
        try:
            outcome = await mcp_client.call_tool("issue_refund", {**body["payload"], "action_id": action_id, "approval_id": body["approval_id"]}, timeout=8)
        except Exception:
            self._transition(action_id, "outcome_unknown")
            return await self._reconcile(action_id)
        if outcome.get("status") in ("committed", "already_committed"):
            result = {**outcome["refund"], "action_id": action_id}
            self._transition(action_id, "succeeded", result)
            return result
        self._transition(action_id, "failed_definitive", outcome)
        raise Blocked("tool_rejected", outcome.get("reason", "rejected by the tool server"))

    async def _reconcile(self, action_id: str) -> dict:
        """Read-only status query; never blindly execute again."""
        status = await mcp_client.call_tool("get_action_status", {"action_id": action_id})
        if status["refunds"]:
            result = {**status["refunds"][0], "action_id": action_id}
            self._transition(action_id, "succeeded", result)
            return {**result, "reconciled": True}
        raise Blocked("outcome_unknown", "refund outcome unknown; held for reconciliation")

    def _transition(self, action_id: str, state: str, result: dict | None = None):
        response = self._api("POST", f"/v1/integration/actions/{action_id}/transition", json={"state": state, "result": result})
        if response.status_code != 200:
            raise Blocked("ledger_conflict", response.text)
