"use client";

import { post, usePoll } from "@assureops/ui/client";
import {
  ApiErrorBanner, Button, Card, CardHeader, EmptyState, Field, inputClass, LoadingState, Mono, Notice, SeverityBadge, StatusBadge, TableWrap, Td, Th,
} from "@assureops/ui/components";
import { EvidenceDrawer } from "@assureops/ui/evidence-drawer";
import { formatTime, pct, shortHash } from "@assureops/ui/format";
import clsx from "clsx";
import { CircleCheck, CircleX, Radio, RefreshCw, Snowflake } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useState } from "react";
import { ActionError, CaseTabs, KeyValue, RevisionDrift, SectionTitle } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import { useStaff } from "@/lib/staff-context";
import type { CaseDetail, ReportDetail } from "@/lib/types";

type Check = { label: string; ok: boolean; detail: string };

function Checklist({ checks }: { checks: Check[] }) {
  return (
    <ul className="space-y-2">
      {checks.map((c) => (
        <li key={c.label} className="flex items-start gap-2 text-sm">
          {c.ok ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-brand-600" aria-hidden /> : <CircleX className="mt-0.5 size-4 shrink-0 text-red-600" aria-hidden />}
          <span><span className="font-medium">{c.label}</span> — <span className={c.ok ? "text-emerald-700" : "text-red-700"}>{c.ok ? "met" : "not met"}</span>
            <span className="block text-xs text-muted">{c.detail}</span></span>
        </li>
      ))}
    </ul>
  );
}

function DecisionForm({ caseId, report, checksFailing, onDone, onReload }: {
  caseId: string; report: ReportDetail; checksFailing: number; onDone: () => void; onReload: () => void;
}) {
  const [loadedRevision] = useState(report.revision);
  const [decision, setDecision] = useState<"publish" | "return">("publish");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const action = useStaffAction(onDone);

  return (
    <form className="space-y-3" onSubmit={async (e) => {
      e.preventDefault();
      const r = await action.run("decide", () => post<{ report_id: string; state: string; case_state: string }>(`/v1/staff/cases/${caseId}/reviews`,
        { report_id: report.id, decision, reason: reason.trim(), expected_revision: loadedRevision }));
      if (r) setResult(`Report is now ${r.state}; case moved to ${r.case_state}.`);
    }}>
      <RevisionDrift loaded={loadedRevision} current={report.revision} what="report" onReload={onReload} />
      <fieldset>
        <legend className="mb-1 text-xs font-medium text-muted">Decision</legend>
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="radio" name="report-decision" checked={decision === "publish"} onChange={() => setDecision("publish")} /> Publish to the customer</label>
          <label className="flex items-center gap-2"><input type="radio" name="report-decision" checked={decision === "return"} onChange={() => setDecision("return")} /> Return to the analyst</label>
        </div>
      </fieldset>
      {decision === "publish" && checksFailing > 0 && (
        <Notice tone="warn">{checksFailing} checklist item{checksFailing === 1 ? " is" : "s are"} not met. The API will refuse a stale snapshot or a self-review; consider returning the report instead.</Notice>
      )}
      <Field label="Reason (required, min. 3 characters)" hint="Recorded in the decision history and the audit log.">
        <textarea required minLength={3} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} className={inputClass} />
      </Field>
      <Button type="submit" variant={decision === "publish" ? "primary" : "danger"} disabled={action.busy !== null || reason.trim().length < 3}>
        {action.busy ? "Recording…" : decision === "publish" ? "Publish report" : "Return report"}
      </Button>
      <ActionError error={action.error} />
      {result && <p role="status" className="text-sm text-emerald-700">{result}</p>}
    </form>
  );
}

function ReportView({ caseId, caseData, reportId }: { caseId: string; caseData: CaseDetail; reportId: string }) {
  const { me } = useStaff();
  const { data: report, error, loading, refresh } = usePoll<ReportDetail>(`/v1/staff/cases/${caseId}/reports/${reportId}`, 10000);
  const [drawer, setDrawer] = useState<string | null>(null);
  const [formGeneration, setFormGeneration] = useState(0);
  const closeDrawer = useCallback(() => setDrawer(null), []);

  if (loading && !report) return <LoadingState label="Loading report…" />;
  if (!report) return <ApiErrorBanner error={error} />;

  const snap = report.snapshot;
  const r = snap.readiness;
  const live = report.current_status;
  const unavailable = snap.evidence.filter((e) => !e.available);
  const checks: Check[] = [
    { label: "Consistent snapshot", ok: !!live && live.release === snap.release.version,
      detail: live ? `Report release ${snap.release.version}; current release ${live.release}.` : "No current release could be computed." },
    { label: "Scope note present", ok: !!snap.scope_note?.trim() && !!snap.case.scope_note?.trim(),
      detail: snap.case.scope_note?.trim() ? `Case scope: “${snap.case.scope_note}”` : "The case has no scope note; the report would not state what was assessed." },
    { label: "Evidence available", ok: snap.evidence.length > 0 && unavailable.length === 0,
      detail: snap.evidence.length === 0 ? "The snapshot indexes no evidence." : unavailable.length ? `Unavailable at draft time: ${unavailable.map((e) => e.test_id).join(", ")}` : `${snap.evidence.length} evidence records indexed, all available at draft time.` },
    { label: "You are not the drafter", ok: !!me && me.user !== report.drafted_by,
      detail: `Drafted by ${report.drafted_by}${me ? `; you are ${me.user}` : ""}.` },
    { label: "Snapshot integrity", ok: report.integrity === "verified", detail: `sha256 ${shortHash(report.sha256, 16)} · ${report.integrity}` },
    { label: "Independent reviewer duty", ok: caseData.your_duty === "reviewer", detail: `Your duty on this case: ${caseData.your_duty}.` },
  ];
  const failing = checks.filter((c) => !c.ok).length;

  return (
    <div className="space-y-5">
      {error && <ApiErrorBanner error={error} />}
      {report.state === "superseded" && <Notice tone="warn">This report is superseded: a newer draft or publication replaced it. It is kept for the record and cannot be decided.</Notice>}
      {report.state === "returned" && <Notice tone="warn">This report was returned to the analyst. A new draft is needed for another review.</Notice>}
      {report.state === "published" && <Notice tone="success">Published{report.publication ? ` by ${report.publication.published_by} · ${formatTime(report.publication.at)} (publication ${report.publication.state})` : ""}.</Notice>}
      {report.integrity !== "verified" && <div role="alert"><Notice tone="danger">Integrity check failed: the stored snapshot no longer matches its sha256. Do not publish.</Notice></div>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card className="min-w-0">
          <CardHeader title="Frozen report snapshot" icon={<Snowflake className="size-4" aria-hidden />} count={`report ${report.id} · revision ${report.revision}`}
            action={<StatusBadge status={report.state} />} />
          <div className="space-y-4 px-5 pb-5">
            <dl className="grid gap-3 sm:grid-cols-3">
              <KeyValue label="Release">{snap.release.version}</KeyValue>
              <KeyValue label="Manifest hash"><Mono>{shortHash(snap.release.manifest_hash, 16)}</Mono></KeyValue>
              <KeyValue label="Collection">{snap.release.collection_status}</KeyValue>
              <KeyValue label="Profile">{snap.profile}</KeyValue>
              <KeyValue label="Drafted">{report.drafted_by} · {formatTime(report.created_at)}</KeyValue>
              <KeyValue label="Integrity">{report.integrity === "verified" ? <span className="text-emerald-700">Verified</span> : <span className="text-red-700">Tampered</span>} <Mono>{shortHash(report.sha256, 16)}</Mono></KeyValue>
            </dl>
            <div className="rounded-lg bg-canvas px-4 py-3">
              <p className="flex flex-wrap items-center gap-2 text-sm"><span className="text-xs text-muted">Gate at snapshot</span><StatusBadge status={r.gate.status} /></p>
              <p className="mt-1 text-xs">{r.gate.reason}</p>
              <p className="mt-2 text-xs text-muted">Evidence support {pct(r.scores.evidence_support_pct)} · coverage {pct(r.scores.evidence_coverage_pct)} · {r.scores.controls_supported}/{r.scores.controls_total} controls supported</p>
            </div>
            <p className="text-xs text-muted">{snap.scope_note}</p>
          </div>

          <h3 className="px-5 pb-2 text-sm font-semibold">Controls</h3>
          <TableWrap minWidth="min-w-[620px]">
            <thead><tr><Th>Control</Th><Th>Control result</Th><Th>Evidence validity</Th><Th>Passing</Th><Th>Runtime</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {r.controls.map((c) => (
                <tr key={c.id}>
                  <Td>{c.id} {c.name}</Td>
                  <Td><StatusBadge status={c.result} /></Td>
                  <Td><StatusBadge status={c.evidence_validity} /></Td>
                  <Td>{c.passed}/{c.total}</Td>
                  <Td className="text-xs">{c.runtime_violation ? <span className="font-semibold text-red-700">Verified violation</span> : <span className="text-muted">None</span>}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>

          <h3 className="px-5 pt-4 pb-2 text-sm font-semibold">Findings in snapshot ({snap.findings.length})</h3>
          {snap.findings.length === 0 ? <p className="px-5 pb-4 text-sm text-muted">No findings at snapshot time.</p> : (
            <TableWrap minWidth="min-w-[620px]">
              <thead><tr><Th>Severity</Th><Th>Finding</Th><Th>Control</Th><Th>Finding state</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {snap.findings.map((f) => (
                  <tr key={f.id}>
                    <Td><SeverityBadge severity={f.severity} /></Td>
                    <Td>{f.title}</Td>
                    <Td>{f.control}</Td>
                    <Td><StatusBadge status={f.state} /></Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )}

          <h3 className="px-5 pt-4 pb-2 text-sm font-semibold">Evidence index ({snap.evidence.length})</h3>
          {snap.evidence.length === 0 ? <p className="px-5 pb-4 text-sm text-muted">No evidence indexed.</p> : (
            <TableWrap minWidth="min-w-[760px]">
              <thead><tr><Th>Test</Th><Th>Control</Th><Th>Outcome</Th><Th>Trials</Th><Th>Release</Th><Th>Integrity</Th><Th>Review</Th><Th /></tr></thead>
              <tbody className="divide-y divide-line">
                {snap.evidence.map((e) => (
                  <tr key={e.id}>
                    <Td><p>{e.test_name}</p><Mono>{e.test_id}</Mono></Td>
                    <Td>{e.control}</Td>
                    <Td><StatusBadge status={e.outcome} /></Td>
                    <Td>{e.passed_trials}/{e.trials}</Td>
                    <Td>{e.release}</Td>
                    <Td>{e.available ? <Mono>{shortHash(e.evidence_hash, 10)}</Mono> : <StatusBadge status="unavailable" />}</Td>
                    <Td className="text-xs">{e.review ? `${e.review.decision} by ${e.review.reviewer}` : <span className="text-muted">—</span>}</Td>
                    <Td><button className="text-xs font-medium whitespace-nowrap text-brand-700 hover:underline" onClick={() => setDrawer(e.id)}>Open evidence</button></Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )}
        </Card>

        <div className="min-w-0 space-y-5">
          <Card className="border-dashed p-5">
            <h2 className="flex items-center gap-2 text-[15px] font-semibold"><Radio className="size-4 text-sky-700" aria-hidden />Live current status</h2>
            <p className="mt-1 text-xs text-muted">Computed now from the latest release. Not part of the frozen report.</p>
            {!live ? <p className="mt-3 text-sm text-muted">No current release.</p> : (
              <div className="mt-3 space-y-2 text-sm">
                <p className="flex flex-wrap items-center gap-2"><span className="text-xs text-muted">Current release</span><span className={clsx("font-semibold", live.release !== snap.release.version && "text-red-700")}>{live.release}</span>
                  {live.release !== snap.release.version && <span className="text-xs text-red-700">differs from the report ({snap.release.version})</span>}</p>
                <p className="flex flex-wrap items-center gap-2"><span className="text-xs text-muted">Gate</span><StatusBadge status={live.gate.status} /></p>
                <p className="text-xs">{live.gate.reason}</p>
                <p className="text-xs text-muted">Support {pct(live.scores.evidence_support_pct)} · coverage {pct(live.scores.evidence_coverage_pct)}</p>
              </div>
            )}
          </Card>

          <Card className="p-5">
            <h2 className="text-[15px] font-semibold">Publication checklist</h2>
            <p className="mt-1 mb-3 text-xs text-muted">Guidance for your decision. The API enforces the snapshot and separation-of-duties rules regardless.</p>
            <Checklist checks={checks} />
          </Card>

          <Card className="p-5">
            <h2 className="mb-3 text-[15px] font-semibold">Independent review decision</h2>
            {report.state === "draft" ? <DecisionForm key={`${report.id}-${formGeneration}`} caseId={caseId} report={report} checksFailing={failing} onDone={refresh}
              onReload={() => setFormGeneration((g) => g + 1)} />
              : <p className="text-sm text-muted">Only draft reports can be decided. This report is {report.state}.</p>}
          </Card>

          <Card className="p-5">
            <SectionTitle>Decision history</SectionTitle>
            {report.decisions.length === 0 ? <p className="text-sm text-muted">No decisions yet.</p> : (
              <ol className="space-y-2 text-sm">
                {report.decisions.map((d, i) => (
                  <li key={i} className="rounded-lg border border-line px-3 py-2">
                    <p className="flex flex-wrap items-center gap-2"><StatusBadge status={d.decision === "publish" ? "published" : "returned"} /><span className="text-xs text-muted">{d.reviewer} · {formatTime(d.at)}</span></p>
                    <p className="mt-1 text-[13px]">{d.reason}</p>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>
      </div>
      {drawer && <EvidenceDrawer runId={drawer} onClose={closeDrawer} path={`/v1/staff/cases/${caseId}/evidence`} />}
    </div>
  );
}

function ReviewWorkspace() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const { data, error, loading, refresh } = usePoll<CaseDetail>(`/v1/staff/cases/${id}`, 15000);

  if (loading && !data) return <LoadingState label="Loading case…" />;
  if (!data) {
    return (
      <div className="mx-auto max-w-[1400px]">
        <ApiErrorBanner error={error} />
        <Link href="/review-queue" className="text-sm text-brand-700 hover:underline">← Back to review queue</Link>
      </div>
    );
  }

  const requested = params.get("report");
  const selected = data.reports.find((r) => r.id === requested)?.id ?? data.reports.find((r) => r.state === "draft")?.id ?? data.reports[0]?.id ?? null;

  return (
    <div className="mx-auto max-w-[1400px]">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Link href="/review-queue" className="text-sm text-brand-700 hover:underline">← Review queue</Link>
        <Button onClick={refresh}><RefreshCw className="size-4" aria-hidden /> Refresh</Button>
      </div>
      <div className="mb-4">
        <h1 className="text-xl font-bold tracking-tight">{data.title}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted"><StatusBadge status={data.state} /> Independent review · your duty: {data.your_duty}</p>
      </div>
      <CaseTabs caseId={id} active="review" />
      {error && <ApiErrorBanner error={error} />}
      {requested && !data.reports.some((r) => r.id === requested) && <div className="mb-4"><Notice tone="warn">Report {requested} is not part of this case; showing the latest draft instead.</Notice></div>}
      {data.reports.length === 0 ? (
        <Card><EmptyState title="No reports on this case" body="The analyst has not drafted a report yet." /></Card>
      ) : (
        <>
          <div className="mb-5 flex flex-wrap items-end gap-3">
            <Field label="Report">
              <select value={selected ?? ""} onChange={(e) => router.replace(`/cases/${id}/review?report=${e.target.value}`)} className={`${inputClass} w-auto min-w-72`}>
                {data.reports.map((r) => <option key={r.id} value={r.id}>{r.release} · {r.state} · rev {r.revision} · {r.id}</option>)}
              </select>
            </Field>
          </div>
          {selected && <ReportView key={selected} caseId={id} caseData={data} reportId={selected} />}
        </>
      )}
    </div>
  );
}

export default function ReviewPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading review…" />}>
      <ReviewWorkspace />
    </Suspense>
  );
}
