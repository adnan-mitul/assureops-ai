"use client";

import { usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, LoadingState, Mono, PageHeader, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime, timeAgo } from "@assureops/ui/format";
import { RefreshCw } from "lucide-react";
import Link from "next/link";
import type { ReviewQueueItem } from "@/lib/types";

export default function ReviewQueuePage() {
  const { data, error, loading, refresh } = usePoll<ReviewQueueItem[]>("/v1/staff/review-queue", 10000);

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Review queue" subtitle="Draft reports awaiting independent review on cases where you are the assigned reviewer. Senior reviewers only."
        actions={<Button onClick={refresh}><RefreshCw className="size-4" aria-hidden /> Refresh</Button>} />
      <ApiErrorBanner error={error} />
      <Card>
        <CardHeader title="Drafts awaiting review" count={data ? `${data.length}` : undefined} />
        {loading && !data ? <div className="px-5"><LoadingState label="Loading review queue…" /></div> : !data ? null : data.length === 0 ? (
          <EmptyState title="No drafts awaiting review" body="A report appears here when the case analyst drafts it and you are the case's independent reviewer." />
        ) : (
          <TableWrap minWidth="min-w-[860px]">
            <thead><tr><Th>Case</Th><Th>Release</Th><Th>Drafted by</Th><Th>Gate at draft</Th><Th>Revision</Th><Th>Age</Th><Th /></tr></thead>
            <tbody className="divide-y divide-line">
              {data.map((r) => (
                <tr key={r.report_id}>
                  <Td><p className="font-medium">{r.case_title}</p><Mono>{r.report_id}</Mono></Td>
                  <Td>{r.release}</Td>
                  <Td className="text-muted">{r.drafted_by}</Td>
                  <Td><StatusBadge status={r.gate} /></Td>
                  <Td>{r.revision}</Td>
                  <Td className="whitespace-nowrap text-muted" ><span title={formatTime(r.at)}>{timeAgo(r.at)}</span></Td>
                  <Td className="text-right">
                    <Link href={`/cases/${r.case_id}/review?report=${r.report_id}`} className="rounded-lg bg-brand-700 px-3 py-1.5 text-xs font-medium whitespace-nowrap text-white hover:bg-brand-800">Review</Link>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
      <p className="mt-3 text-xs text-muted">The gate shown is frozen in the draft snapshot; the review screen shows the live status separately.</p>
    </div>
  );
}
