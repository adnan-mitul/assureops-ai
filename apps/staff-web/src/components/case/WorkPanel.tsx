"use client";

import { post } from "@assureops/ui/client";
import { Button, Card, CardHeader, EmptyState, Mono, Notice, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime, shortHash, timeAgo } from "@assureops/ui/format";
import { ClipboardList, FilePlus2, Play, RotateCcw } from "lucide-react";
import Link from "next/link";
import { ActionDone, ActionError } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import type { AssessmentJob, CaseDetail } from "@/lib/types";

function steps(job: AssessmentJob) {
  const done = job.steps.filter((s) => s.status === "done").length;
  return `${done}/${job.steps.length}`;
}

export function AnalystActions({ data, onChange }: { data: CaseDetail; onChange: () => void }) {
  const action = useStaffAction(onChange);
  const running = data.overview.assessment?.running ?? null;
  const notAnalyst = data.your_duty !== "analyst";

  return (
    <Card className="mb-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-semibold">Analyst actions</h2>
          <p className="mt-1 text-xs text-muted">
            {notAnalyst ? "Your duty on this case is independent reviewer; the API refuses analyst actions from you (separation of duties)."
              : "Runs and drafts are recorded against your name. Drafting freezes a snapshot for independent review."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" disabled={action.busy !== null}
            onClick={() => action.run("full", () => post<{ id: string; tests: string[] }>(`/v1/staff/cases/${data.id}/assessments`, { scope: "full" }), "Full assessment queued.")}>
            <Play className="size-4" aria-hidden /> {action.busy === "full" ? "Queuing…" : "Run full assessment"}
          </Button>
          <Button disabled={action.busy !== null}
            onClick={() => action.run("retest", () => post(`/v1/staff/cases/${data.id}/assessments`, { scope: "retest" }), "Retest queued for stale, failed and unverified tests.")}>
            <RotateCcw className="size-4" aria-hidden /> {action.busy === "retest" ? "Queuing…" : "Run retest"}
          </Button>
          <Button disabled={action.busy !== null}
            onClick={() => action.run("draft", () => post<{ id: string; sha256: string }>(`/v1/staff/cases/${data.id}/reports`), "Report drafted; it now awaits independent review.")}>
            <FilePlus2 className="size-4" aria-hidden /> {action.busy === "draft" ? "Drafting…" : "Draft report"}
          </Button>
        </div>
      </div>
      <div className="mt-3 space-y-2">
        {running && (
          <Notice tone="info">
            <span role="status">Assessment <Mono>{running.id}</Mono> is {running.status}: {steps(running)} steps done.</span> The API refuses a second run and a report draft until it finishes, so the snapshot stays consistent.
          </Notice>
        )}
        <ActionError error={action.error} />
        <ActionDone message={action.done} />
      </div>
    </Card>
  );
}

export function AssessmentsPanel({ jobs }: { jobs: AssessmentJob[] }) {
  return (
    <Card className="mb-5">
      <CardHeader title="Assessments" icon={<ClipboardList className="size-4" aria-hidden />} count={`latest ${jobs.length}`} />
      {jobs.length === 0 ? <EmptyState title="No assessments yet" body="Run a full assessment once the customer has submitted a release." /> : (
        <TableWrap minWidth="min-w-[900px]">
          <thead><tr><Th>Job</Th><Th>Release</Th><Th>Scope</Th><Th>Job state</Th><Th>Steps</Th><Th>Requested by</Th><Th>Created</Th><Th>Finished</Th></tr></thead>
          <tbody className="divide-y divide-line">
            {jobs.map((j) => (
              <tr key={j.id}>
                <Td><Mono>{j.id}</Mono>{j.error && <p role="note" className="text-xs text-red-700">Error: {j.error}</p>}{j.cancel_requested && <p className="text-xs text-amber-700">Cancellation requested</p>}</Td>
                <Td>{j.release ?? "—"}</Td>
                <Td className="capitalize">{j.scope}</Td>
                <Td><StatusBadge status={j.status} /></Td>
                <Td>{steps(j)}{j.steps.some((s) => s.status === "failed") && <span className="ml-1 text-xs text-red-700">({j.steps.filter((s) => s.status === "failed").length} failed)</span>}</Td>
                <Td className="text-muted">{j.requested_by}</Td>
                <Td className="whitespace-nowrap text-muted">{formatTime(j.created_at)}</Td>
                <Td className="whitespace-nowrap text-muted">{j.finished_at ? timeAgo(j.finished_at) : "—"}</Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </Card>
  );
}

export function ReportsPanel({ data }: { data: CaseDetail }) {
  return (
    <Card className="mb-5">
      <CardHeader title="Reports" count={`${data.reports.length}`} />
      {data.reports.length === 0 ? <EmptyState title="No reports drafted" body="The analyst drafts a report to freeze a snapshot for independent review." /> : (
        <TableWrap minWidth="min-w-[760px]">
          <thead><tr><Th>Report</Th><Th>Report state</Th><Th>Release</Th><Th>Drafted by</Th><Th>Revision</Th><Th>Drafted</Th><Th /></tr></thead>
          <tbody className="divide-y divide-line">
            {data.reports.map((r) => (
              <tr key={r.id}>
                <Td><Mono>{r.id}</Mono><p><Mono>sha256 {shortHash(r.sha256, 12)}</Mono></p></Td>
                <Td><StatusBadge status={r.state} /></Td>
                <Td>{r.release}</Td>
                <Td className="text-muted">{r.drafted_by}</Td>
                <Td>{r.revision}</Td>
                <Td className="whitespace-nowrap text-muted">{formatTime(r.at)}</Td>
                <Td className="text-right"><Link href={`/cases/${data.id}/review?report=${r.id}`} className="text-xs font-medium text-brand-700 hover:underline">Open in review</Link></Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </Card>
  );
}
