"use client";

import type { ApiError } from "@assureops/ui/client";
import { Notice } from "@assureops/ui/components";
import clsx from "clsx";
import { EyeOff, Users } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import type { Assignee, Duty } from "@/lib/types";

/** Explains why the API refused an action; the API is the source of truth for every rule. */
export function ActionError({ error }: { error: ApiError | null }) {
  if (!error) return null;
  let title = "Action failed";
  let tone = "border-red-200 bg-red-50 text-red-700";
  if (error.code === "separation_of_duties") {
    title = "Separation of duties";
    tone = "border-amber-200 bg-amber-50 text-amber-800";
  } else if (error.status === 403) {
    title = "Permission denied";
    tone = "border-amber-200 bg-amber-50 text-amber-800";
  } else if (error.code === "stale_revision") {
    title = "Stale revision — reloaded the latest version";
    tone = "border-amber-200 bg-amber-50 text-amber-800";
  } else if (error.status === 409) {
    title = "Refused by current state";
    tone = "border-amber-200 bg-amber-50 text-amber-800";
  } else if (error.status === 422) {
    title = "Not accepted";
  }
  return (
    <div role="alert" className={clsx("rounded-lg border px-3 py-2 text-sm", tone)}>
      <span className="font-semibold">{title}:</span> {error.message}
      {error.code && error.code !== "error" && <span className="ml-1 font-mono text-[11px] opacity-80">({error.code})</span>}
    </div>
  );
}

export function ActionDone({ message }: { message: string | null }) {
  if (!message) return null;
  return <p role="status" className="text-sm text-emerald-700">{message}</p>;
}

export function DutyBadge({ duty }: { duty: Duty | null | undefined }) {
  if (!duty) return <span className="text-xs text-muted">Not assigned</span>;
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
      duty === "analyst" ? "bg-sky-50 text-sky-700" : "bg-violet-50 text-violet-700")}>
      {duty === "analyst" ? "Analyst" : "Independent reviewer"}
    </span>
  );
}

export function Assignees({ assignees }: { assignees: Assignee[] }) {
  if (assignees.length === 0) return <span className="text-xs text-muted">Unassigned</span>;
  return (
    <ul className="space-y-0.5">
      {assignees.map((a) => (
        <li key={`${a.user}-${a.duty}`} className="text-xs whitespace-nowrap"><span className="text-ink">{a.user ?? "unknown user"}</span> <span className="text-muted">· {a.duty}</span></li>
      ))}
    </ul>
  );
}

export function VisibilityBadge({ visibility }: { visibility: "internal" | "customer" }) {
  return visibility === "internal" ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-800 px-2 py-0.5 text-xs font-medium text-white"><EyeOff className="size-3" aria-hidden />Internal note — staff only</span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700 ring-1 ring-sky-200 ring-inset"><Users className="size-3" aria-hidden />Visible to customer</span>
  );
}

export function KeyValue({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-[13px] break-words text-ink">{children}</dd>
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{children}</h3>;
}

const CASE_TABS = [
  { key: "workspace", label: "Case workspace", suffix: "" },
  { key: "investigation", label: "Investigation", suffix: "/investigation" },
  { key: "review", label: "Review", suffix: "/review" },
] as const;

export function CaseTabs({ caseId, active }: { caseId: string; active: (typeof CASE_TABS)[number]["key"] }) {
  return (
    <nav aria-label="Case sections" className="mb-5 flex flex-wrap gap-1 border-b border-line text-sm">
      {CASE_TABS.map((t) => (
        <Link key={t.key} href={`/cases/${caseId}${t.suffix}`} aria-current={active === t.key ? "page" : undefined}
          className={clsx("-mb-px border-b-2 px-3 py-2", active === t.key ? "border-brand-700 font-semibold text-brand-700" : "border-transparent text-gray-600 hover:text-ink")}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

/** Shown when the object behind an open form changed after the form was opened. */
export function RevisionDrift({ loaded, current, what, onReload }: { loaded: number; current: number | undefined; what: string; onReload?: () => void }) {
  if (current === undefined || current === loaded) return null;
  return (
    <Notice tone="warn">
      This {what} changed since you opened the form (revision {loaded} → {current}). Submitting will be refused as stale;{" "}
      {onReload ? <button type="button" className="font-medium underline" onClick={onReload}>review the latest revision</button> : "close and reopen the form to review the latest version"}.
    </Notice>
  );
}

export function hoursLabel(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 48) return `${hours.toFixed(1)}h`;
  return `${Math.round(hours / 24)}d`;
}

export function secondsLabel(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${Math.round(seconds / 86400)}d`;
}
