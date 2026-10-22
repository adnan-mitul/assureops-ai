"""Caller identity.

Users authenticate with the maintained OIDC provider. The API validates issuer,
audience, expiry and signature, then resolves roles from current database
memberships; the token and browser never supply roles or workspaces. Staff and
customer tokens have distinct audiences. Machines use scoped service credentials.
"""

import hashlib
import os
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select

from assureops_domain.config import settings
from assureops_domain.db import platform_session
from assureops_domain.models import EventSource, Membership, ServiceCredential, StaffRole, User

# Customers and staff authenticate in separate realms; each surface accepts only its own issuer and audience.
_jwks = {issuer: jwt.PyJWKClient(f"{issuer}/protocol/openid-connect/certs", cache_keys=True, lifespan=300)
         for issuer in (settings().customer_issuer, settings().staff_issuer)}


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Caller:
    user_id: str
    username: str
    display_name: str
    kind: str  # customer | staff
    workspace_id: str | None = None
    role: str | None = None
    memberships: dict = field(default_factory=dict)  # workspace_id -> role
    staff_roles: set = field(default_factory=set)

    def require_role(self, *roles: str):
        if self.role not in roles:
            raise api_error(403, "forbidden", f"your role ({self.role}) cannot perform this action")

    def require_staff(self, *roles: str):
        if not self.staff_roles & set(roles):
            raise api_error(403, "forbidden", "your staff role cannot perform this action")


def _verify(authorization: str | None, audience: str, issuer: str) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise api_error(401, "unauthenticated", "sign in required")
    token = authorization.removeprefix("Bearer ")
    try:
        key = _jwks[issuer].get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=["RS256"], audience=audience, issuer=issuer,
                          options={"require": ["exp", "iss", "aud", "sub"]})
    except jwt.InvalidAudienceError:
        raise api_error(403, "wrong_audience", "this token is not valid for this API surface")
    except jwt.PyJWTError as exc:
        raise api_error(401, "invalid_token", f"token rejected: {exc.__class__.__name__}")


def _load_user(claims: dict, kind: str) -> Caller:
    username = claims.get("preferred_username") or claims.get("email")
    with platform_session() as s:
        user = s.scalars(select(User).where(User.username == username, User.active.is_(True))).first()
        if user is None or user.kind != kind:
            raise api_error(403, "no_access", "your account has no access to this portal")
        caller = Caller(user.id, user.username, user.display_name, user.kind)
        if kind == "customer":
            caller.memberships = {m.workspace_id: m.role for m in s.scalars(select(Membership).where(Membership.user_id == user.id, Membership.active.is_(True)))}
        else:
            caller.staff_roles = {r.role for r in s.scalars(select(StaffRole).where(StaffRole.user_id == user.id, StaffRole.active.is_(True)))}
    return caller


def customer(authorization: str | None = Header(default=None), x_workspace_id: str | None = Header(default=None)) -> Caller:
    caller = _load_user(_verify(authorization, settings().customer_audience, settings().customer_issuer), "customer")
    if not caller.memberships:
        raise api_error(403, "no_membership", "you are not a member of any workspace")
    workspace = x_workspace_id or next(iter(caller.memberships))
    if workspace not in caller.memberships:  # revoked or never granted: deny, never trust the header
        raise api_error(403, "no_membership", "you are not a member of this workspace")
    caller.workspace_id, caller.role = workspace, caller.memberships[workspace]
    return caller


def staff_mfa_required() -> bool:
    from assureops_domain.config import _dev_env

    return (os.environ.get("STAFF_MFA_REQUIRED") or _dev_env().get("STAFF_MFA_REQUIRED") or "true").lower() == "true"


def _has_second_factor(claims: dict) -> bool:
    """The staff realm's OTP step adds "otp" to the authentication-method references of the session's tokens."""
    amr = claims.get("amr") or []
    return isinstance(amr, list) and "otp" in amr


def staff(authorization: str | None = Header(default=None)) -> Caller:
    claims = _verify(authorization, settings().staff_audience, settings().staff_issuer)
    if staff_mfa_required() and not _has_second_factor(claims):
        raise api_error(403, "mfa_required", "staff access requires a second factor; sign in again with your one-time code")
    caller = _load_user(claims, "staff")
    if not caller.staff_roles:
        raise api_error(403, "no_staff_role", "no active staff role")
    return caller


@dataclass
class Service:
    kind: str
    workspace_id: str
    application_id: str
    environment: str
    credential_id: str | None = None


def service(*kinds: str):
    def dependency(authorization: str | None = Header(default=None)) -> Service:
        if not authorization or not authorization.startswith("Bearer "):
            raise api_error(401, "unauthenticated", "service credential required")
        with platform_session() as s:
            cred = s.scalars(select(ServiceCredential).where(ServiceCredential.token_hash == token_hash(authorization.removeprefix("Bearer ")),
                                                             ServiceCredential.revoked.is_(False))).first()
        if cred is None or cred.kind not in kinds:
            raise api_error(403, "forbidden", "credential not valid for this operation")
        return Service(cred.kind, cred.workspace_id, cred.application_id, cred.environment, cred.id)
    return dependency


def event_source(authorization: str | None = Header(default=None)) -> EventSource:
    if not authorization or not authorization.startswith("Bearer "):
        raise api_error(401, "unauthenticated", "source credential required")
    with platform_session() as s:
        source = s.scalars(select(EventSource).where(EventSource.token_hash == token_hash(authorization.removeprefix("Bearer ")),
                                                     EventSource.revoked.is_(False))).first()
    if source is None:
        raise api_error(403, "forbidden", "unknown or revoked event source")
    return source


def request_id(request: Request) -> str:
    return request.state.request_id


CustomerCaller = Depends(customer)
StaffCaller = Depends(staff)
