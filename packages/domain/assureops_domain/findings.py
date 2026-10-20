"""Findings and incidents.

A finding closes only through valid retest evidence or an audited reviewer
determination. A generic pass never closes a runtime incident; closure is an
explicit, revision-checked reviewer operation.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Finding, Incident, Release, TestRun, now


class FindingError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def record_test_outcome(session: Session, run: TestRun, release: Release, p: dict):
    test = p["tests_by_id"][run.test_id]
    rows = session.scalars(select(Finding).where(Finding.application_id == run.application_id, Finding.test_id == run.test_id,
                                                 Finding.source == "test").order_by(Finding.created_at.desc())).all()
    active = next((f for f in rows if f.state != "resolved"), None)
    ref = {"run_id": run.id, "release": release.version, "outcome": run.outcome}
    if run.outcome == "failed":
        if active:
            active.last_release = release.version
            active.evidence_refs = [*active.evidence_refs, ref]
            active.revision += 1
            active.updated_at = now()
        elif rows:  # a new failure after resolution reopens the same finding
            latest = rows[0]
            latest.state, latest.last_release, latest.revision, latest.updated_at = "reopened", release.version, latest.revision + 1, now()
            latest.evidence_refs = [*latest.evidence_refs, ref]
            latest.resolution = None
        else:
            session.add(Finding(
                workspace_id=run.workspace_id, application_id=run.application_id, control_id=test["control"], test_id=test["id"],
                source="test", severity=test["severity"], title=test["name"],
                description=f"Expected: {run.expected}. Failed {run.trials - run.passed_trials} of {run.trials} trials on {release.version}.",
                first_release=release.version, last_release=release.version, evidence_refs=[ref],
            ))
    elif run.outcome == "passed" and active and run.passed_trials == run.trials:
        active.state = "resolved"
        active.resolution = {"by": "retest", "run_id": run.id, "release": release.version, "at": now()}
        active.evidence_refs = [*active.evidence_refs, ref]
        active.revision += 1
        active.updated_at = now()


def open_runtime_violation(session: Session, *, workspace_id: str, application_id: str, control_id: str, release: str,
                           event_revision: int, description: str, severity: str = "critical",
                           title: str = "Verified unauthorized effect in operation") -> Incident:
    rows = session.scalars(select(Finding).where(Finding.application_id == application_id, Finding.control_id == control_id,
                                                 Finding.source == "runtime").order_by(Finding.created_at.desc())).all()
    finding = next((f for f in rows if f.state != "resolved"), None)
    if finding is None and rows:
        finding = rows[0]
        finding.state, finding.resolution, finding.revision = "reopened", None, finding.revision + 1
    if finding is None:
        finding = Finding(workspace_id=workspace_id, application_id=application_id, control_id=control_id, source="runtime",
                          severity=severity, title=title,
                          description=description, first_release=release, last_release=release, evidence_refs=[])
        session.add(finding)
        session.flush()
    finding.last_release = release
    finding.evidence_refs = [*finding.evidence_refs, {"event_revision": event_revision, "release": release}]
    finding.updated_at = now()
    open_same = session.scalars(select(Incident).where(Incident.application_id == application_id, Incident.control_id == control_id,
                                                       Incident.cohort == release, Incident.state == "open").with_for_update()).first()
    if open_same is not None:  # same control and cohort: one incident accumulates its verified events
        open_same.event_revisions = [*open_same.event_revisions, event_revision]
        open_same.revision += 1
        return open_same
    incident = Incident(workspace_id=workspace_id, application_id=application_id, control_id=control_id, severity=severity,
                        title=finding.title, release=release, cohort=release, event_revisions=[event_revision], finding_id=finding.id)
    session.add(incident)
    session.flush()
    return incident


def close_incident(session: Session, incident: Incident, *, expected_revision: int, reviewer: str, note: str, state: dict) -> dict:
    """Requires current passing evidence for the control on a release other than the affected cohort."""
    if incident.revision != expected_revision:
        raise FindingError("stale_revision", "incident changed since you loaded it; reload and review again")
    if incident.state == "closed":
        raise FindingError("already_closed", "incident is already closed")
    if not note.strip():
        raise FindingError("note_required", "a closure note is required")
    if state["release"]["version"] == incident.cohort:
        raise FindingError("same_release", f"deploy and assess a remediated release; {incident.cohort} is the affected release")
    tests = [t for t in state["tests"] if t["control"] == incident.control_id]
    unproven = [t["test_id"] for t in tests if not (t["result"] == "supported" and t["validity"] == "current")]
    if unproven:
        raise FindingError("evidence_missing", f"current passing retest evidence missing for: {', '.join(unproven)}")
    closure = {"by": "reviewer", "reviewer": reviewer, "note": note, "release": state["release"]["version"],
               "run_ids": [t["run_id"] for t in tests], "at": now()}
    incident.state, incident.closure, incident.revision = "closed", closure, incident.revision + 1
    others = session.scalars(select(Incident).where(Incident.finding_id == incident.finding_id, Incident.id != incident.id,
                                                    Incident.state != "closed")).first()
    finding = session.get(Finding, incident.finding_id)
    if finding and not others:
        finding.state, finding.resolution, finding.revision, finding.updated_at = "resolved", closure, finding.revision + 1, now()
    return closure
