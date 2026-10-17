"use client";

import { usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, LoadingState, Notice, PageHeader } from "@assureops/ui/components";
import clsx from "clsx";
import { Cpu, Inbox, ListChecks, RefreshCw, Server, Workflow } from "lucide-react";
import type { ReactNode } from "react";
import { secondsLabel } from "@/components/staff-ui";
import type { Operations } from "@/lib/types";

function Metric({ label, value, warn, hint }: { label: string; value: ReactNode; warn?: boolean; hint?: string }) {
  return (
    <div className="rounded-lg bg-canvas px-4 py-3">
      <p className="text-xs text-muted">{label}</p>
      <p className={clsx("mt-0.5 text-xl font-bold", warn && "text-amber-700")}>{value}{warn && <span className="sr-only"> (needs attention)</span>}</p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

export default function OperationsPage() {
  const { data, error, loading, refresh } = usePoll<Operations>("/v1/staff/operations", 10000);

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Operations" subtitle="Platform health: queue depths, job states and ingestion rates."
        actions={<Button onClick={refresh}><RefreshCw className="size-4" aria-hidden /> Refresh</Button>} />
      <div className="mb-4 space-y-2">
        <Notice>Platform metadata only — counts and ages. No customer content, evidence or messages appear on this page.</Notice>
        <ApiErrorBanner error={error} />
      </div>
      {loading && !data ? <LoadingState label="Loading platform health…" /> : !data ? null : (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader title="Outbox" icon={<Inbox className="size-4" aria-hidden />} />
            <div className="grid gap-3 px-5 pb-5 sm:grid-cols-2">
              <Metric label="Pending dispatch" value={data.outbox.pending} warn={data.outbox.pending > 0 && data.outbox.oldest_age_seconds > 300} />
              <Metric label="Oldest pending" value={data.outbox.pending ? secondsLabel(data.outbox.oldest_age_seconds) : "—"} warn={data.outbox.oldest_age_seconds > 300}
                hint={data.outbox.oldest_age_seconds > 300 ? "Older than 5 minutes: check the dispatcher" : undefined} />
            </div>
          </Card>
          <Card>
            <CardHeader title="Job steps" icon={<ListChecks className="size-4" aria-hidden />} />
            <div className="grid gap-3 px-5 pb-5 grid-cols-2 sm:grid-cols-4">
              <Metric label="Pending" value={data.steps.pending} />
              <Metric label="Running" value={data.steps.running} />
              <Metric label="Expired leases" value={data.steps.expired_leases} warn={data.steps.expired_leases > 0} hint="Running steps past their lease" />
              <Metric label="Failed" value={data.steps.failed} warn={data.steps.failed > 0} />
            </div>
          </Card>
          <Card>
            <CardHeader title="Assessment jobs (last 24 h)" icon={<Workflow className="size-4" aria-hidden />} />
            <div className="grid gap-3 px-5 pb-5 sm:grid-cols-3">
              <Metric label="Queued" value={data.jobs.queued} />
              <Metric label="Running" value={data.jobs.running} />
              <Metric label="Failed" value={data.jobs.failed_last_day} warn={data.jobs.failed_last_day > 0} />
            </div>
          </Card>
          <Card>
            <CardHeader title="Runtime ingestion" icon={<Server className="size-4" aria-hidden />} />
            <div className="grid gap-3 px-5 pb-5 sm:grid-cols-2">
              <Metric label="Events, last 5 minutes" value={data.ingestion.events_last_5_minutes} hint="Across all workspaces with cases" />
            </div>
          </Card>
          <Card className="lg:col-span-2">
            <CardHeader title="Inference and runner" icon={<Cpu className="size-4" aria-hidden />} />
            <dl className="grid gap-4 px-5 pb-5 sm:grid-cols-2">
              <div>
                <dt className="text-xs text-muted">Inference routes enabled</dt>
                <dd className="mt-0.5 text-sm"><span className="font-semibold">{data.inference.routes_enabled}</span> — {data.inference.note}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">Test runner isolation</dt>
                <dd className="mt-0.5 text-sm"><span className="font-semibold">{data.runner.isolation}</span> — {data.runner.note}</dd>
              </div>
            </dl>
          </Card>
        </div>
      )}
    </div>
  );
}
