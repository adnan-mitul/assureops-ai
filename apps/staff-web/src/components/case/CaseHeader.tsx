"use client";

import { Card, Mono, StatusBadge } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import clsx from "clsx";
import { Check } from "lucide-react";
import { Assignees, DutyBadge, KeyValue } from "@/components/staff-ui";
import type { CaseDetail } from "@/lib/types";

const MAIN_PATH = ["submitted", "triage", "assessment", "awaiting_review", "published", "monitoring"] as const;
const LABEL: Record<string, string> = {
  submitted: "Submitted", triage: "Triage", assessment: "Assessment", awaiting_review: "Awaiting review", published: "Published", monitoring: "Monitoring",
};
// Side states sit beside the main path: they are shown where they branch off.
const SIDE: Record<string, { anchor: string; label: string }> = {
  awaiting_customer: { anchor: "assessment", label: "Awaiting customer" },
  reassessment: { anchor: "monitoring", label: "Reassessment" },
  draft: { anchor: "", label: "Draft (not yet submitted)" },
};

export function StateTimeline({ state }: { state: string }) {
  const side = SIDE[state];
  const currentIndex = MAIN_PATH.indexOf((side ? side.anchor : state) as (typeof MAIN_PATH)[number]);
  return (
    <div>
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-2 text-xs" aria-label="Case state">
        {MAIN_PATH.map((s, i) => {
          const done = currentIndex > i;
          const current = currentIndex === i;
          return (
            <li key={s} className="flex items-center gap-1" aria-current={current ? "step" : undefined}>
              <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 whitespace-nowrap",
                current && !side ? "bg-brand-700 font-semibold text-white" : current ? "bg-amber-50 font-semibold text-amber-700 ring-1 ring-amber-300 ring-inset"
                  : done ? "bg-brand-50 text-brand-700" : "bg-gray-100 text-gray-500")}>
                {done && <Check className="size-3" aria-hidden />}
                {LABEL[s]}
                {current && !side && <span className="sr-only">(current state)</span>}
                {current && side && <span className="sr-only">(branched to {side.label})</span>}
                {done && <span className="sr-only">(passed)</span>}
              </span>
              {i < MAIN_PATH.length - 1 && <span className="text-gray-300" aria-hidden>›</span>}
            </li>
          );
        })}
      </ol>
      {side && <p className="mt-2 text-xs"><span className="rounded-full bg-amber-50 px-2 py-0.5 font-semibold text-amber-700">Current: {side.label}</span></p>}
    </div>
  );
}

function ScopeValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) return <>{value.length ? value.map(String).join(", ") : "—"}</>;
  if (value && typeof value === "object") return <Mono>{JSON.stringify(value)}</Mono>;
  return <>{value === null || value === undefined || value === "" ? "—" : String(value)}</>;
}

export function CaseHeader({ data }: { data: CaseDetail }) {
  const app = data.application;
  const scope = Object.entries(app.authorized_scope ?? {});
  return (
    <Card className="mb-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted">Assessment case · <Mono>{data.id}</Mono></p>
          <h1 className="mt-1 text-xl font-bold tracking-tight">{data.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={data.state} />
            <span className="rounded-full bg-canvas px-2 py-0.5 text-muted capitalize">Priority: {data.priority}</span>
            <span className="text-muted">Your duty:</span> <DutyBadge duty={data.your_duty} />
            <span className="text-muted">Case revision {data.revision} · updated {formatTime(data.updated_at)}</span>
          </div>
        </div>
        <div className="text-sm">
          <p className="text-xs font-medium text-muted">Assignees</p>
          <div className="mt-1"><Assignees assignees={data.assignees} /></div>
        </div>
      </div>
      <div className="mt-4"><StateTimeline state={data.state} /></div>
      <dl className="mt-5 grid gap-4 border-t border-line pt-4 sm:grid-cols-2 xl:grid-cols-4">
        <KeyValue label="Application">{app.name} <Mono>{app.id}</Mono></KeyValue>
        <KeyValue label="Mode · environment"><span className="capitalize">{app.mode.replaceAll("_", " ")}</span> · <span className="capitalize">{app.environment}</span></KeyValue>
        <KeyValue label="Purpose" className="sm:col-span-2">{app.purpose || "—"}</KeyValue>
        <KeyValue label="Case scope note" className="sm:col-span-2">{data.scope_note || <span className="text-amber-700">No scope note recorded</span>}</KeyValue>
        <div className="sm:col-span-2">
          <dt className="text-xs text-muted">Authorized scope</dt>
          <dd className="mt-0.5">
            {scope.length === 0 ? <span className="text-[13px] text-amber-700">No authorized scope recorded</span> : (
              <ul className="space-y-0.5 text-[13px]">
                {scope.map(([k, v]) => <li key={k}><span className="text-muted">{k.replaceAll("_", " ")}:</span> <ScopeValue value={v} /></li>)}
              </ul>
            )}
          </dd>
        </div>
      </dl>
    </Card>
  );
}
