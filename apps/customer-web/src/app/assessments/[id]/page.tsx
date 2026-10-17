"use client";

import { post, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, LoadingState, Mono, Notice, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { EvidenceDrawer } from "@assureops/ui/evidence-drawer";
import { formatTime, pct } from "@assureops/ui/format";
import clsx from "clsx";
import { CircleStop, FolderKanban, ListChecks, Loader2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";
import { Fact, PageTop, useRouteId, WithSuspense } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { AssessmentCase, AssessmentJob, Evidence } from "@/lib/types";

const STATUS_NOTE: Record<AssessmentJob["status"], { tone: "info" | "warn" | "danger" | "success"; text: string }> = {
  queued: { tone: "info", text: "Queued: waiting for a worker to pick up the first step." },
  running: { tone: "info", text: "Running: steps execute against the exact release; results below appear as each step finishes." },
  awaiting_review: { tone: "warn", text: "Awaiting review: all steps finished, but semantic results need reviewer confirmation before the affected controls count as supported. Until then the release gate stays incomplete." },
  completed: { tone: "success", text: "Completed: every step reached a terminal state and the readiness result was recomputed." },
  failed: { tone: "danger", text: "Failed: no evidence was attributed to this release." },
  cancelled: { tone: "warn", text: "Cancelled: steps that had not started were skipped. Evidence from finished steps is kept." },
};

function AssessmentView() {
  const id = useRouteId();
  const { applicationId, canWrite } = useApp();
  const [drawer, setDrawer] = useState<string | null>(null);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const { data: job, error, loading, refresh } = usePoll<AssessmentJob>(`/v1/assessments/${encodeURIComponent(id)}`, 2000);
  const active = job?.status === "queued" || job?.status === "running";
  const { data: evidence } = usePoll<Evidence[]>(applicationId && job ? `/v1/evidence?application_id=${encodeURIComponent(applicationId)}` : null, active ? 2000 : 0);
  const { data: kase } = usePoll<AssessmentCase>(job?.case_id ? `/v1/customer/cases/${encodeURIComponent(job.case_id)}` : null, 15000);
  const { busy, error: actionError, run } = useAction();

  if (loading && !job) return <LoadingState label="Loading assessment…" />;
  if (!job) return <ApiErrorBanner error={error} />;

  const runs = new Map((evidence ?? []).map((e) => [e.id, e]));
  const done = job.steps.filter((s) => s.status === "done").length;
  const terminal = job.steps.filter((s) => s.status !== "pending" && s.status !== "running").length;
  const note = STATUS_NOTE[job.status];
  const openRequests = kase?.evidence_requests.filter((r) => r.state === "open").length ?? 0;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Assessments" title={`Assessment ${job.id}`} subtitle={`${job.scope === "full" ? "Full assessment" : "Retest"} of release ${job.release ?? "—"}`}
        actions={<>
          <StatusBadge status={job.status} />
          {active && canWrite && (
            <Button variant="danger" disabled={!!busy || job.cancel_requested} onClick={() => run("cancel", () => post(`/v1/assessments/${encodeURIComponent(job.id)}/cancel`), refresh)}>
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <CircleStop className="size-4" aria-hidden />} {job.cancel_requested ? "Cancel requested" : "Cancel assessment"}
            </Button>
          )}
        </>} />

      <div className="mb-4 space-y-2">
        <ApiErrorBanner error={error} />
        {actionError && <div role="alert"><Notice tone="danger">{actionError}</Notice></div>}
        <Notice tone={note.tone}>{note.text}{job.status === "failed" && job.error ? ` Reason: ${job.error}` : ""}</Notice>
        {job.status !== "failed" && job.error && <Notice tone="warn">{job.error}. Infrastructure errors are not proof of an application defect; those tests remain unverified.</Notice>}
        {active && job.cancel_requested && <Notice tone="warn">Cancellation requested. Steps already running finish; the rest are skipped.</Notice>}
      </div>

      <Card className="p-5">
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="Scope"><span className="capitalize">{job.scope}</span> · {job.tests.length} tests</Fact>
          <Fact label="Plan id"><Mono>{job.plan_id}</Mono></Fact>
          <Fact label="Profile">{job.profile_version}</Fact>
          <Fact label="Requested by">{job.requested_by}</Fact>
          <Fact label="Started">{formatTime(job.created_at)}</Fact>
          <Fact label="Finished">{formatTime(job.finished_at)}</Fact>
          <Fact label="Progress">{done}/{job.steps.length} steps done · {terminal - done} other terminal</Fact>
          <Fact label="Result">
            {job.summary?.gate ? <><StatusBadge status={job.summary.gate} label={`Gate ${job.summary.gate}`} />
              {job.summary.scores && <span className="block pt-1 text-xs font-normal text-muted">Support {pct(job.summary.scores.evidence_support_pct)} · coverage {pct(job.summary.scores.evidence_coverage_pct)}</span>}</>
              : <span className="text-muted">{active ? "Partial: see steps below" : "Not computed"}</span>}
          </Fact>
        </dl>
        <div className="mt-4 h-2 rounded-full bg-gray-100" role="progressbar" aria-label="Steps finished" aria-valuenow={terminal} aria-valuemin={0} aria-valuemax={job.steps.length || 1}>
          <div className={clsx("h-2 rounded-full", job.status === "cancelled" || job.status === "failed" ? "bg-gray-400" : "bg-brand-600")}
            style={{ width: `${job.steps.length ? (terminal / job.steps.length) * 100 : 100}%` }} />
        </div>
      </Card>

      {job.case_id && (
        <Card className="mt-5 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-start gap-3">
              <FolderKanban className="mt-0.5 size-5 text-muted" aria-hidden />
              <div>
                <p className="text-xs text-muted">Assessment case</p>
                <p className="font-semibold">{kase?.title ?? job.case_id}</p>
                {kase && <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted"><StatusBadge status={kase.state} />{openRequests ? `${openRequests} open evidence request(s)` : "No open evidence requests"}</p>}
              </div>
            </div>
            <Link href={`/cases/${job.case_id}`} className="rounded-lg border border-line px-3.5 py-2 text-sm font-medium hover:bg-canvas">Respond to requests</Link>
          </div>
        </Card>
      )}

      <Card className="mt-5">
        <CardHeader title="Steps" icon={<ListChecks className="size-4" aria-hidden />} count={`${job.steps.length}`} />
        {job.steps.length === 0 ? <EmptyState title="No steps planned" body="The plan contained no tests; the readiness result was recomputed without running anything." /> : (
          <TableWrap minWidth="min-w-[760px]">
            <thead><tr><Th>#</Th><Th>Test</Th><Th>Step status</Th><Th>Attempt</Th><Th>Test outcome</Th><Th>Error</Th><Th /></tr></thead>
            <tbody className="divide-y divide-line">
              {job.steps.map((s, i) => {
                const ev = s.run_id ? runs.get(s.run_id) : undefined;
                return (
                  <tr key={s.test_id}>
                    <Td className="text-muted">{i + 1}</Td>
                    <Td>{ev && <p>{ev.test_name}</p>}<Mono>{s.test_id}</Mono></Td>
                    <Td><StatusBadge status={s.status} label={s.status === "failed" ? "Infrastructure error" : undefined} /></Td>
                    <Td>{s.attempt}</Td>
                    <Td>{ev ? <><StatusBadge status={ev.outcome} /><span className="block pt-1 text-xs text-muted">{ev.passed_trials}/{ev.trials} trials</span></>
                      : <span className="text-xs text-muted">{s.run_id ? "Loading…" : s.status === "pending" || s.status === "running" ? "Not finished" : "No evidence recorded"}</span>}</Td>
                    <Td className="max-w-xs text-xs break-words text-red-700">{s.error ?? <span className="text-muted">—</span>}</Td>
                    <Td>{s.run_id && <button type="button" className="text-xs font-medium text-brand-700 hover:underline" onClick={() => setDrawer(s.run_id!)}>Open evidence</button>}</Td>
                  </tr>
                );
              })}
            </tbody>
          </TableWrap>
        )}
      </Card>
      {drawer && <EvidenceDrawer runId={drawer} onClose={closeDrawer} />}
    </div>
  );
}

export default function AssessmentPage() {
  return <WithSuspense label="Loading assessment…"><AssessmentView /></WithSuspense>;
}
