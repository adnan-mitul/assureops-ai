"use client";

import { usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, ControlStateBadges, EmptyState, LoadingState, Mono, Notice, SeverityBadge, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { EvidenceDrawer } from "@assureops/ui/evidence-drawer";
import { formatTime, pct, shortHash } from "@assureops/ui/format";
import { Download, Printer, Radio, ShieldAlert, ShieldCheck, Snowflake } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";
import { Fact, PageTop, ScoreSummary, useRouteId, WithSuspense } from "@/components/bits";
import type { ReportDetail, ReportListItem } from "@/lib/types";

function ReportView() {
  const id = useRouteId();
  const [drawer, setDrawer] = useState<string | null>(null);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const { data: report, error, loading } = usePoll<ReportDetail>(`/v1/reports/${encodeURIComponent(id)}`, 30000);
  const appId = report?.snapshot.application.id;
  const superseded = report?.state === "superseded" || report?.publication?.state === "superseded";
  const { data: list } = usePoll<ReportListItem[]>(superseded && appId ? `/v1/reports?application_id=${encodeURIComponent(appId)}` : null, 0);

  if (loading && !report) return <LoadingState label="Loading report…" />;
  if (!report) return <ApiErrorBanner error={error} />;

  const snap = report.snapshot;
  const r = snap.readiness;
  const latest = list?.find((p) => p.state === "published" && p.report_id !== report.id);
  const current = report.current_status;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Reports" title={`Readiness report · ${snap.release.version}`} subtitle={`${snap.application.name} · ${snap.application.environment}`}
        actions={<span className="flex gap-2 print:hidden">
          <a href={`/api/v1/reports/${encodeURIComponent(report.id)}/export`} download
            className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium hover:bg-canvas focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600">
            <Download className="size-4" aria-hidden /> Evidence bundle
          </a>
          <Button onClick={() => window.print()}><Printer className="size-4" aria-hidden /> Print</Button>
        </span>} />

      <div className="mb-4 space-y-2">
        <ApiErrorBanner error={error} />
        {superseded && (
          <Notice tone="warn">Superseded: a newer report replaced this one. It remains a valid record of {snap.release.version} at the time it was published.
            {latest && <> <Link className="underline" href={`/reports/${latest.report_id}`}>Open the current report ({latest.release})</Link></>}</Notice>
        )}
        {report.integrity === "verified"
          ? <Notice tone="success"><span className="inline-flex items-center gap-2"><ShieldCheck className="size-4" aria-hidden />Integrity verified: the snapshot matches its sealed SHA-256 <span className="font-mono text-xs break-all">{report.sha256}</span></span></Notice>
          : <div role="alert"><Notice tone="danger"><span className="inline-flex items-center gap-2"><ShieldAlert className="size-4" aria-hidden />Integrity check failed: the stored snapshot does not match its sealed hash. Do not rely on this report.</span></Notice></div>}
      </div>

      <section aria-labelledby="current-status" className="mb-5 rounded-xl border-2 border-dashed border-sky-300 bg-sky-50/60 p-5 print:hidden">
        <h2 id="current-status" className="flex items-center gap-2 text-[15px] font-semibold text-sky-900"><Radio className="size-4" aria-hidden />Current status (live, not part of the frozen report)</h2>
        {current ? (
          <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-sky-900">
            <span>Latest release <strong>{current.release}</strong>{current.release !== snap.release.version && " (differs from the reported release)"}</span>
            <span className="flex items-center gap-2">Gate <StatusBadge status={current.gate.status} /></span>
            <ScoreSummary scores={current.scores} />
            <p className="w-full text-xs">{current.gate.reason}</p>
          </div>
        ) : <p className="mt-2 text-sm text-sky-900">No release is currently collected for this application.</p>}
      </section>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold"><Snowflake className="size-4" aria-hidden />Frozen snapshot</h2>
          <p className="text-xs text-muted">Generated {formatTime(snap.generated_at)} · revision {report.revision}</p>
        </div>
        <div className="px-5 py-4">
          <Notice tone="info">{snap.scope_note}</Notice>
          <dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Fact label="Application">{snap.application.name} <span className="font-normal text-muted">· {snap.application.mode.replaceAll("_", " ")}</span></Fact>
            <Fact label="Assessment case">{snap.case.title}</Fact>
            <Fact label="Release">{snap.release.version} <Mono>#{shortHash(snap.release.manifest_hash, 12)}</Mono></Fact>
            <Fact label="Collection">{snap.release.collection_status === "complete" ? "Complete" : "Partial: evidence reuse was not allowed"}</Fact>
            <Fact label="Profile">{snap.profile}</Fact>
            <Fact label="Gate policy">{r.profile.gate_policy}</Fact>
            <Fact label="Drafted by">{report.drafted_by}</Fact>
            <Fact label="Published">{report.publication ? `${report.publication.published_by} · ${formatTime(report.publication.at)}` : "Not published"}</Fact>
          </dl>
          {snap.case.scope_note && <p className="mt-4 text-sm"><span className="text-xs text-muted">Case scope: </span>{snap.case.scope_note}</p>}
        </div>

        <div className="grid gap-4 border-t border-line px-5 py-4 md:grid-cols-2">
          <div>
            <p className="text-xs text-muted">Release gate at snapshot</p>
            <p className="mt-1"><StatusBadge status={r.gate.status} /></p>
            <p className="mt-1 text-sm">{r.gate.reason}</p>
            {([["Blocking", r.gate.blocking], ["Incomplete", r.gate.incomplete], ["Warnings", r.gate.warnings]] as const).filter(([, items]) => items.length > 0).map(([label, items]) => (
              <p key={label} className="mt-1 text-xs text-muted">{label}: {items.join("; ")}</p>
            ))}
          </div>
          <div>
            <p className="text-xs text-muted">Scores at snapshot</p>
            <dl className="mt-1 grid grid-cols-2 gap-3">
              <Fact label="Evidence support">{pct(r.scores.evidence_support_pct)}</Fact>
              <Fact label="Evidence coverage">{pct(r.scores.evidence_coverage_pct)}</Fact>
              <Fact label="Controls supported">{r.scores.controls_supported}/{r.scores.controls_total}</Fact>
              <Fact label="Controls covered">{r.scores.controls_covered}/{r.scores.controls_total}</Fact>
              <Fact label="Tests current and passing">{r.counts.tests_current_passing}/{r.counts.tests_total}</Fact>
              <Fact label="Open findings">{r.counts.open_findings} ({r.counts.critical_open} critical)</Fact>
            </dl>
            <p className="mt-2 text-xs text-muted">Evidence support is not a probability of safety.</p>
          </div>
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="Controls" count={`${r.controls.length}`} />
        <TableWrap minWidth="min-w-[640px]">
          <thead><tr><Th>Control</Th><Th>Family</Th><Th>Result and evidence</Th><Th>Tests passing</Th><Th>Runtime</Th></tr></thead>
          <tbody className="divide-y divide-line">
            {r.controls.map((c) => (
              <tr key={c.id}>
                <Td className="whitespace-nowrap">{c.id} {c.name}</Td>
                <Td className="text-muted">{c.family}</Td>
                <Td><ControlStateBadges result={c.result} validity={c.evidence_validity} />{c.evidence_validity === "current" && <span className="sr-only">, evidence current</span>}</Td>
                <Td>{c.passed}/{c.total}</Td>
                <Td className="text-xs">{c.runtime_violation ? <span className="font-medium text-red-700">Verified violation</span> : <span className="text-muted">None recorded</span>}</Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      </Card>

      <Card className="mt-5">
        <CardHeader title="Findings at snapshot" count={`${snap.findings.length}`} />
        {snap.findings.length === 0 ? <EmptyState title="No findings" body="No finding existed for this application when the snapshot was taken." /> : (
          <TableWrap minWidth="min-w-[640px]">
            <thead><tr><Th>Severity</Th><Th>Control</Th><Th>Finding</Th><Th>State then</Th><Th>Releases</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {snap.findings.map((f) => (
                <tr key={f.id}>
                  <Td><SeverityBadge severity={f.severity} /></Td>
                  <Td className="whitespace-nowrap">{f.control} {f.control_name}</Td>
                  <Td><p>{f.title}</p><span className="text-xs text-muted">{f.source === "runtime" ? "Verified runtime violation" : `Test ${f.test_id}`}</span></Td>
                  <Td><StatusBadge status={f.state} /></Td>
                  <Td className="text-xs whitespace-nowrap">{f.first_release} → {f.last_release}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>

      <Card className="mt-5">
        <CardHeader title="Evidence index" count={`${snap.evidence.length} runs`} />
        {snap.evidence.length === 0 ? <EmptyState title="No evidence referenced" body="The snapshot references no test runs." /> : (
          <TableWrap minWidth="min-w-[720px]">
            <thead><tr><Th>Test</Th><Th>Control</Th><Th>Release</Th><Th>Outcome</Th><Th>SHA-256 at snapshot</Th><Th className="print:hidden" /></tr></thead>
            <tbody className="divide-y divide-line">
              {snap.evidence.map((e) => (
                <tr key={e.id}>
                  <Td><p>{e.test_name}</p><Mono>{e.test_id} · {e.id}</Mono></Td>
                  <Td>{e.control}</Td>
                  <Td>{e.release}</Td>
                  <Td><StatusBadge status={e.outcome} /><span className="block pt-1 text-xs text-muted">{e.passed_trials}/{e.trials} trials</span></Td>
                  <Td>{e.available ? <Mono>{shortHash(e.evidence_hash, 16)}</Mono> : <StatusBadge status="unavailable" />}</Td>
                  <Td className="print:hidden"><button type="button" className="text-xs font-medium whitespace-nowrap text-brand-700 hover:underline" onClick={() => setDrawer(e.id)}>Open evidence</button></Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
        <p className="px-5 py-3 text-xs text-muted">Opening a run shows the stored evidence record as it is now; its hash should match the value frozen above.</p>
      </Card>

      <p className="mt-5 text-xs text-muted">Scope: readiness within the tested boundary of release {snap.release.version} in {snap.application.environment}, under profile {snap.profile}. This report is not a certification, compliance attestation or launch approval.</p>
      {drawer && <EvidenceDrawer runId={drawer} onClose={closeDrawer} />}
    </div>
  );
}

export default function ReportPage() {
  return <WithSuspense label="Loading report…"><ReportView /></WithSuspense>;
}
