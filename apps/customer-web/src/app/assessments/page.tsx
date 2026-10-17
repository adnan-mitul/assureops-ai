"use client";

import { newIdempotencyKey, post, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, EmptyState, LoadingState, Mono, Notice, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime, pct } from "@assureops/ui/format";
import { FlaskConical, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { PageTop } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { AssessmentCreated, AssessmentJob } from "@/lib/types";

export default function AssessmentsPage() {
  const { applicationId, canWrite } = useApp();
  const router = useRouter();
  const { data, error, loading, refresh } = usePoll<AssessmentJob[]>(applicationId ? `/v1/assessments?application_id=${encodeURIComponent(applicationId)}` : null, 3000);
  const { busy, error: actionError, run } = useAction();

  if (!applicationId || (loading && !data)) return <LoadingState label="Loading assessments…" />;
  if (!data) return <ApiErrorBanner error={error} />;

  const running = data.find((j) => j.status === "queued" || j.status === "running");
  const start = () => run("full", async () => {
    const job = await post<AssessmentCreated>("/v1/assessments", { application_id: applicationId, scope: "full" }, newIdempotencyKey());
    router.push(`/assessments/${job.id}`);
  }, refresh);

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Assessments" title="Assessment runs" subtitle="Full assessments run every test in the profile; retests run only the plan computed from a change set."
        actions={canWrite ? (
          <Button variant="primary" disabled={!!busy || !!running} onClick={start}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <FlaskConical className="size-4" aria-hidden />} {running ? "Assessment running…" : "Full assessment"}
          </Button>
        ) : <p className="text-xs text-muted">Your role can view assessments but cannot start them.</p>} />
      <div className="mb-4 space-y-2">
        <ApiErrorBanner error={error} />
        {actionError && <div role="alert"><Notice tone="danger">{actionError}</Notice></div>}
        {running && <Notice tone="info">Assessment {running.id} is {running.status}. <Link className="underline" href={`/assessments/${running.id}`}>Follow progress</Link></Notice>}
      </div>

      <Card>
        {data.length === 0 ? <EmptyState title="No assessments yet" body="Submit a release, then start a full assessment or request a retest from a change set." /> : (
          <TableWrap minWidth="min-w-[960px]">
            <thead><tr><Th>Assessment</Th><Th>Release</Th><Th>Scope</Th><Th>Status</Th><Th>Steps</Th><Th>Result</Th><Th>Requested by</Th><Th>Started</Th><Th>Finished</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {data.map((j) => {
                const done = j.steps.filter((s) => s.status === "done").length;
                return (
                  <tr key={j.id}>
                    <Td><Link href={`/assessments/${j.id}`} className="font-medium hover:underline">{j.id}</Link><span className="block"><Mono>plan {j.plan_id}</Mono></span></Td>
                    <Td>{j.release ?? "—"}</Td>
                    <Td className="capitalize">{j.scope}</Td>
                    <Td><StatusBadge status={j.status} />{j.cancel_requested && j.status !== "cancelled" && <span className="block pt-1 text-xs text-muted">Cancel requested</span>}</Td>
                    <Td className="whitespace-nowrap">{done}/{j.steps.length} done</Td>
                    <Td>
                      {j.summary?.gate ? <><StatusBadge status={j.summary.gate} label={`Gate ${j.summary.gate}`} />
                        {j.summary.scores && <span className="block pt-1 text-xs text-muted">Support {pct(j.summary.scores.evidence_support_pct)} · coverage {pct(j.summary.scores.evidence_coverage_pct)}</span>}</>
                        : <span className="text-xs text-muted">{j.status === "cancelled" ? "Cancelled before a result" : "No result yet"}</span>}
                      {j.error && <span className="block pt-1 text-xs text-red-700">{j.error}</span>}
                    </Td>
                    <Td>{j.requested_by}</Td>
                    <Td className="whitespace-nowrap text-muted">{formatTime(j.created_at)}</Td>
                    <Td className="whitespace-nowrap text-muted">{formatTime(j.finished_at)}</Td>
                  </tr>
                );
              })}
            </tbody>
          </TableWrap>
        )}
      </Card>
    </div>
  );
}
