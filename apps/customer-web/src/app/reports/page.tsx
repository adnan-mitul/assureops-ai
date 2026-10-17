"use client";

import { usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Card, EmptyState, LoadingState, Mono, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime, shortHash } from "@assureops/ui/format";
import Link from "next/link";
import { PageTop } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { ReportListItem } from "@/lib/types";

export default function ReportsPage() {
  const { applicationId } = useApp();
  const { data, error, loading } = usePoll<ReportListItem[]>(applicationId ? `/v1/reports?application_id=${encodeURIComponent(applicationId)}` : null, 15000);

  if (!applicationId || (loading && !data)) return <LoadingState label="Loading reports…" />;
  if (!data) return <ApiErrorBanner error={error} />;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Reports" title="Published readiness reports"
        subtitle="Each report is a frozen, hash-sealed snapshot of one release within its tested boundary. It is not a certification." />
      <ApiErrorBanner error={error} />
      <Card>
        {data.length === 0 ? <EmptyState title="No published reports" body="Reports are drafted and published by AssureOps staff after an assessment case is reviewed." /> : (
          <TableWrap minWidth="min-w-[720px]">
            <thead><tr><Th>Report</Th><Th>Release</Th><Th>State</Th><Th>SHA-256</Th><Th>Published by</Th><Th>Published</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {data.map((r) => (
                <tr key={`${r.report_id}-${r.at}`}>
                  <Td><Link href={`/reports/${r.report_id}`} className="font-medium hover:underline">{r.report_id}</Link></Td>
                  <Td>{r.release}</Td>
                  <Td><StatusBadge status={r.state} />{r.state === "superseded" && <span className="block pt-1 text-xs text-muted">A newer report replaced it</span>}</Td>
                  <Td><Mono>{shortHash(r.sha256, 16)}</Mono></Td>
                  <Td>{r.published_by}</Td>
                  <Td className="whitespace-nowrap text-muted">{formatTime(r.at)}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
    </div>
  );
}
