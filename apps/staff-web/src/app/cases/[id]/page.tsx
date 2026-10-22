"use client";

import { usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, LoadingState } from "@assureops/ui/components";
import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense } from "react";
import { CaseHeader } from "@/components/case/CaseHeader";
import { EvidenceRequests, MessageThread } from "@/components/case/CaseConversation";
import { FindingsPanel } from "@/components/case/FindingsPanel";
import { ReadinessPanel } from "@/components/case/ReadinessPanel";
import { SetupPanel } from "@/components/case/SetupPanel";
import { TestEvidence } from "@/components/case/TestEvidence";
import { AnalystActions, AssessmentsPanel, ReportsPanel } from "@/components/case/WorkPanel";
import { CaseTabs } from "@/components/staff-ui";
import type { CaseDetail } from "@/lib/types";

function CaseWorkspace() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, refresh } = usePoll<CaseDetail>(`/v1/staff/cases/${id}`, 6000);

  if (loading && !data) return <LoadingState label="Loading case…" />;
  if (!data) {
    return (
      <div className="mx-auto max-w-[1400px]">
        <ApiErrorBanner error={error} />
        <Link href="/work-queue" className="text-sm text-brand-700 hover:underline">← Back to work queue</Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1400px]">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Link href="/work-queue" className="text-sm text-brand-700 hover:underline">← Work queue</Link>
        <Button onClick={refresh}><RefreshCw className="size-4" aria-hidden /> Refresh</Button>
      </div>
      {error && <ApiErrorBanner error={error} />}
      <CaseHeader data={data} />
      <CaseTabs caseId={data.id} active="workspace" />
      <SetupPanel data={data} onChange={refresh} />
      <AnalystActions data={data} onChange={refresh} />
      <ReadinessPanel overview={data.overview} />
      {data.overview.readiness && <TestEvidence caseId={data.id} readiness={data.overview.readiness} duty={data.your_duty} onChange={refresh} />}
      <FindingsPanel caseId={data.id} findings={data.findings} duty={data.your_duty} onChange={refresh} />
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="min-w-0"><AssessmentsPanel jobs={data.assessments} /></div>
        <div className="min-w-0"><ReportsPanel data={data} /></div>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="min-w-0"><MessageThread data={data} onChange={refresh} /></div>
        <div className="min-w-0"><EvidenceRequests data={data} onChange={refresh} /></div>
      </div>
    </div>
  );
}

export default function CasePage() {
  return (
    <Suspense fallback={<LoadingState label="Loading case…" />}>
      <CaseWorkspace />
    </Suspense>
  );
}
