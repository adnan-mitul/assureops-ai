"use client";

import { LoadingState } from "@assureops/ui/components";
import { pct } from "@assureops/ui/format";
import { useParams } from "next/navigation";
import { Suspense, type ReactNode } from "react";
import type { Readiness } from "@/lib/types";

/** Page heading in the same layout as the dashboard header. */
export function PageTop({ eyebrow, title, subtitle, actions }: { eyebrow: string; title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="text-sm font-medium text-muted">{eyebrow}</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight break-words">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Fact({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium break-words">{children}</dd>
    </div>
  );
}

export function ScoreSummary({ scores }: { scores: Readiness["scores"] }) {
  return (
    <span>
      Evidence support {pct(scores.evidence_support_pct)} · coverage {pct(scores.evidence_coverage_pct)} · {scores.controls_supported}/{scores.controls_total} controls supported
    </span>
  );
}

/** Wraps a page that reads URL data, as Cache Components requires. */
export function WithSuspense({ children, label }: { children: ReactNode; label?: string }) {
  return <Suspense fallback={<LoadingState label={label} />}>{children}</Suspense>;
}

export function useRouteId(): string {
  const { id } = useParams<{ id: string }>();
  return decodeURIComponent(id);
}
