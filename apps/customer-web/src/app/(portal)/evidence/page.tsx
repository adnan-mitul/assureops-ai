"use client";

import { usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Card, EmptyState, LoadingState, Mono, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { EvidenceDrawer } from "@assureops/ui/evidence-drawer";
import { formatTime, shortHash } from "@assureops/ui/format";
import { useCallback, useState } from "react";
import { PageTop } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { Evidence } from "@/lib/types";

export default function EvidencePage() {
  const { applicationId } = useApp();
  const [drawer, setDrawer] = useState<string | null>(null);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const { data, error, loading } = usePoll<Evidence[]>(applicationId ? `/v1/evidence?application_id=${encodeURIComponent(applicationId)}` : null, 10000);

  if (!applicationId || (loading && !data)) return <LoadingState label="Loading evidence…" />;
  if (!data) return <ApiErrorBanner error={error} />;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Evidence" title="Test evidence" subtitle="Every recorded test run for this application, newest first (up to 150). Whether a run still counts for the current release is shown on the dashboard." />
      <ApiErrorBanner error={error} />
      <Card>
        {data.length === 0 ? <EmptyState title="No evidence recorded" body="Evidence is recorded when an assessment step finishes." /> : (
          <TableWrap minWidth="min-w-[960px]">
            <thead><tr><Th>Test</Th><Th>Control</Th><Th>Release</Th><Th>Outcome</Th><Th>Trials</Th><Th>Availability</Th><Th>Review</Th><Th>Recorded</Th><Th /></tr></thead>
            <tbody className="divide-y divide-line">
              {data.map((e) => (
                <tr key={e.id}>
                  <Td><p>{e.test_name}</p><Mono>{e.test_id}</Mono></Td>
                  <Td className="whitespace-nowrap">{e.control} {e.control_name}</Td>
                  <Td>{e.release}</Td>
                  <Td><StatusBadge status={e.outcome} /></Td>
                  <Td className="whitespace-nowrap">{e.passed_trials}/{e.trials} passed
                    <span className="mt-1 flex gap-0.5" aria-hidden>{e.trial_outcomes.map((ok, i) => <span key={i} className={`size-2 rounded-sm ${ok === null ? "bg-gray-400" : ok ? "bg-brand-600" : "bg-red-600"}`} />)}</span></Td>
                  <Td>{e.available ? <><span className="text-xs">Available</span><span className="block"><Mono>sha256 {shortHash(e.evidence_hash, 10)}</Mono></span></> : <StatusBadge status="unavailable" />}</Td>
                  <Td>{e.review ? <StatusBadge status={e.review.decision === "accept" ? "accepted" : "rejected"} label={`${e.review.decision === "accept" ? "Accepted" : "Rejected"} by ${e.review.reviewer}`} /> : <span className="text-xs text-muted">No review</span>}</Td>
                  <Td className="whitespace-nowrap text-muted">{formatTime(e.created_at)}</Td>
                  <Td><button type="button" className="text-xs font-medium whitespace-nowrap text-brand-700 hover:underline" onClick={() => setDrawer(e.id)}>Open evidence</button></Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
      {drawer && <EvidenceDrawer runId={drawer} onClose={closeDrawer} />}
    </div>
  );
}
