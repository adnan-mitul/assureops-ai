"use client";

import { usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Card, EmptyState, LoadingState, StatusBadge } from "@assureops/ui/components";
import { pct } from "@assureops/ui/format";
import { ArrowRight, Bot, GitBranch } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { PageTop } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { ApplicationSummary } from "@/lib/types";

export default function ApplicationsPage() {
  const { applicationId, setApplicationId } = useApp();
  const router = useRouter();
  const { data, error, loading } = usePoll<ApplicationSummary[]>("/v1/applications", 15000);

  if (loading && !data) return <LoadingState label="Loading applications…" />;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Applications" title="AI applications in this workspace" subtitle="Each application is assessed per exact release. Gate and evidence figures come from its latest collected release." />
      <ApiErrorBanner error={error} />
      {data && data.length === 0 && <Card><EmptyState title="No applications registered" body="A workspace owner registers an application before releases can be collected." /></Card>}
      <div className="grid gap-4 lg:grid-cols-2">
        {data?.map((a) => (
          <Card key={a.id} className="flex flex-col p-5">
            <div className="flex items-start gap-4">
              <span className="grid size-11 shrink-0 place-items-center rounded-lg bg-gray-900 text-white"><Bot className="size-5" aria-hidden /></span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold">{a.name}</h2>
                  <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700 capitalize">{a.environment}</span>
                  <span className="rounded-full bg-canvas px-2 py-0.5 text-xs text-muted">{a.mode.replaceAll("_", " ")}</span>
                  {a.id === applicationId && <span className="rounded-full bg-sky-50 px-2 py-0.5 text-xs text-sky-700">Selected on dashboard</span>}
                </div>
                <p className="mt-0.5 text-sm text-muted">{a.description}</p>
                <p className="mt-1 font-mono text-[11px] text-muted">{a.id}</p>
              </div>
            </div>

            <dl className="mt-4 grid gap-3 rounded-lg bg-canvas p-4 text-sm sm:grid-cols-3">
              <div><dt className="text-xs text-muted">Current release</dt><dd className="mt-0.5 font-semibold">{a.release ?? "None collected"}</dd></div>
              <div><dt className="text-xs text-muted">Release gate</dt><dd className="mt-0.5">{a.gate ? <StatusBadge status={a.gate.status} /> : <StatusBadge status="unverified" label="Not assessed" />}</dd></div>
              <div><dt className="text-xs text-muted">Evidence support</dt>
                <dd className="mt-0.5">{a.scores ? <>{pct(a.scores.evidence_support_pct)}<span className="block text-xs text-muted">coverage {pct(a.scores.evidence_coverage_pct)} · {a.scores.controls_supported}/{a.scores.controls_total} supported</span></> : "—"}</dd></div>
            </dl>
            <p className="mt-3 text-xs text-muted">{a.gate ? a.gate.reason : "No release has been submitted yet, so no gate has been computed."}</p>

            <div className="mt-auto flex flex-wrap gap-2 pt-4">
              <Link href={`/applications/${encodeURIComponent(a.id)}/releases`} className="inline-flex items-center gap-2 rounded-lg border border-line px-3.5 py-2 text-sm font-medium hover:bg-canvas">
                <GitBranch className="size-4" aria-hidden /> Releases
              </Link>
              <button type="button" onClick={() => { setApplicationId(a.id); router.push("/overview"); }}
                className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-3.5 py-2 text-sm font-medium text-white hover:bg-brand-800">
                Open dashboard <ArrowRight className="size-4" aria-hidden />
              </button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
