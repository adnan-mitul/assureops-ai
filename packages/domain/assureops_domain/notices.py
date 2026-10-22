"""Application notice board and change notifications.

Every application has a notice board its workspace members read. People post notices (a planned
release, a question for the reviewer); the platform posts change notices itself (a release with
changed components, a profile waiting for a second person, AI proposals waiting for review, an
assessment that finished). Each notice also becomes a notification for the application's team:
owners, reviewers and the developers currently assigned to it, never its author. Notifications are
shown in the portal and delivered by the dispatcher through the mail transport and the signed webhook.
Notices carry descriptions only, never evidence content or credentials.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import platform_session
from .handoffs import notify
from .models import AppNotice, Application, ApplicationGrant, Membership, User, now

TEAM_ROLES = ("owner", "reviewer")
MAX_BODY = 4000


def team(session: Session, app: Application) -> list[str]:
    """Usernames that hear about this application: owners and reviewers of its workspace plus its assigned developers."""
    granted = [g.user_id for g in session.scalars(select(ApplicationGrant).where(ApplicationGrant.application_id == app.id,
                                                                                 ApplicationGrant.revoked_at.is_(None)))
               if g.expires_at is None or g.expires_at > now()]
    with platform_session() as p:
        rows = p.execute(select(User.username, Membership.role, User.id).join(Membership, Membership.user_id == User.id)
                         .where(Membership.workspace_id == app.workspace_id)).all()
    return sorted({name for name, role, uid in rows if role in TEAM_ROLES or (role == "developer" and uid in granted)})


def post(session: Session, app: Application, *, author: str, subject: str, body: str, kind: str = "notice") -> AppNotice:
    """Record a notice on the board and notify the team (in-app, then mail and webhook through the dispatcher)."""
    notice = AppNotice(workspace_id=app.workspace_id, application_id=app.id, author=author, kind=kind, subject=subject[:200],
                       body=body[:MAX_BODY])
    session.add(notice)
    recipients = [u for u in team(session, app) if u != author]
    with platform_session() as p:
        for username in recipients:
            notify(p, recipient=username, kind=f"app_{kind}", workspace_id=app.workspace_id, subject=f"[{app.name}] {subject}"[:200],
                   body=f"{body[:MAX_BODY]}\n\nApplication: {app.name} ({app.id}). Posted by {author}.\n")
    return notice


def change(session: Session, app: Application, *, subject: str, body: str) -> AppNotice:
    """A notice the platform posts itself when something about the application changed or waits for someone."""
    return post(session, app, author="assureops", subject=subject, body=body, kind="change")


def case_message(session: Session, case, *, author: str, author_kind: str, visibility: str, body: str) -> int:
    """Tell the other side of an assessment case about a new message. Internal staff notes never notify customers."""
    from .models import CaseAssignment

    app = session.get(Application, case.application_id)
    if author_kind == "customer":
        with platform_session() as p:
            ids = [a.staff_user_id for a in p.scalars(select(CaseAssignment).where(CaseAssignment.case_id == case.id,
                                                                                   CaseAssignment.active.is_(True)))]
            recipients = sorted(u.username for u in p.scalars(select(User).where(User.id.in_(ids)))) if ids else []
    elif visibility == "customer":
        recipients = team(session, app)
    else:
        return 0
    recipients = [r for r in recipients if r != author]
    with platform_session() as p:
        for username in recipients:
            notify(p, recipient=username, kind="case_message", workspace_id=case.workspace_id, subject=f"New message on case: {case.title}"[:200],
                   body=f"{author} wrote on the case for {app.name}:\n\n{body[:MAX_BODY]}\n")
    return len(recipients)
