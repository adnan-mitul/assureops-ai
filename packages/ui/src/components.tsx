import clsx from "clsx";
import { AlertTriangle, CircleCheck, CircleHelp, Clock3, Info, OctagonAlert, XCircle } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={clsx("rounded-xl border border-line bg-surface", className)}>{children}</section>;
}

export function CardHeader({ title, icon, action, count }: { title: string; icon?: ReactNode; action?: ReactNode; count?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 px-5 pt-4 pb-3">
      <div className="flex items-center gap-2">
        {icon}
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
        {count && <span className="text-xs text-muted">{count}</span>}
      </div>
      {action}
    </div>
  );
}

export function ViewAll({ href, label = "View all" }: { href: string; label?: string }) {
  return (
    <Link href={href} className="text-xs font-medium text-brand-600 hover:text-brand-700">
      {label} →
    </Link>
  );
}

export function Button({
  children, onClick, variant = "secondary", disabled, className, type = "button", ariaLabel, pressed,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger";
  disabled?: boolean;
  className?: string;
  type?: "button" | "submit";
  ariaLabel?: string;
  pressed?: boolean;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-pressed={pressed}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" && "bg-brand-700 text-white hover:bg-brand-800",
        variant === "secondary" && "border border-line bg-surface text-ink hover:bg-canvas",
        variant === "danger" && "border border-red-200 bg-red-50 text-red-700 hover:bg-red-100",
        className,
      )}
    >
      {children}
    </button>
  );
}

const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-red-50 text-red-700 ring-red-200",
  high: "bg-orange-50 text-orange-700 ring-orange-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  low: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  unknown: "bg-gray-100 text-gray-700 ring-gray-200",
  none: "bg-gray-50 text-gray-500 ring-gray-200",
};

export function SeverityBadge({ severity }: { severity: string }) {
  const Icon = severity === "critical" ? OctagonAlert : severity === "high" || severity === "medium" ? AlertTriangle : Info;
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium capitalize ring-1 ring-inset", SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.unknown)}>
      <Icon className="size-3" aria-hidden />
      {severity}
    </span>
  );
}

const GOOD = "bg-emerald-50 text-emerald-700";
const WARN = "bg-amber-50 text-amber-700";
const BAD = "bg-red-50 text-red-700";
const NEUTRAL = "bg-gray-100 text-gray-600";
const INFO = "bg-sky-50 text-sky-700";

// One vocabulary per state dimension (plan §6); never a single green/red field.
const STATUS: Record<string, { label: string; style: string; icon: typeof CircleCheck }> = {
  // control_result
  supported: { label: "Supported", style: GOOD, icon: CircleCheck },
  failed: { label: "Failed", style: BAD, icon: XCircle },
  unverified: { label: "Unverified", style: NEUTRAL, icon: CircleHelp },
  review_required: { label: "Review required", style: WARN, icon: Clock3 },
  not_applicable: { label: "Not applicable", style: NEUTRAL, icon: CircleHelp },
  // evidence_validity
  current: { label: "Current", style: GOOD, icon: CircleCheck },
  stale: { label: "Stale", style: WARN, icon: Clock3 },
  unavailable: { label: "Evidence unavailable", style: NEUTRAL, icon: CircleHelp },
  unassessed: { label: "Not assessed", style: NEUTRAL, icon: CircleHelp },
  not_collected: { label: "Outside profile", style: NEUTRAL, icon: CircleHelp },
  reused: { label: "Reused", style: INFO, icon: CircleCheck },
  // test outcome
  passed: { label: "Passed", style: GOOD, icon: CircleCheck },
  error: { label: "Infrastructure error", style: NEUTRAL, icon: CircleHelp },
  // assessment_job
  queued: { label: "Queued", style: WARN, icon: Clock3 },
  running: { label: "Running", style: WARN, icon: Clock3 },
  awaiting_review: { label: "Awaiting review", style: WARN, icon: Clock3 },
  completed: { label: "Completed", style: GOOD, icon: CircleCheck },
  cancelled: { label: "Cancelled", style: NEUTRAL, icon: XCircle },
  pending: { label: "Pending", style: NEUTRAL, icon: Clock3 },
  done: { label: "Done", style: GOOD, icon: CircleCheck },
  // finding_state
  open: { label: "Open", style: BAD, icon: XCircle },
  under_review: { label: "Under review", style: WARN, icon: Clock3 },
  resolved: { label: "Resolved", style: GOOD, icon: CircleCheck },
  reopened: { label: "Reopened", style: BAD, icon: XCircle },
  // runtime coverage
  degraded: { label: "Degraded", style: WARN, icon: Clock3 },
  unknown: { label: "Unknown", style: NEUTRAL, icon: CircleHelp },
  not_connected: { label: "Not connected", style: NEUTRAL, icon: CircleHelp },
  up: { label: "Up", style: GOOD, icon: CircleCheck },
  unreachable: { label: "Unreachable", style: BAD, icon: XCircle },
  // gate
  blocked: { label: "Blocked", style: BAD, icon: XCircle },
  incomplete: { label: "Incomplete", style: WARN, icon: Clock3 },
  ready: { label: "Ready", style: GOOD, icon: CircleCheck },
  // case and report
  draft: { label: "Draft", style: NEUTRAL, icon: Clock3 },
  submitted: { label: "Submitted", style: INFO, icon: Clock3 },
  triage: { label: "Triage", style: INFO, icon: Clock3 },
  assessment: { label: "Assessment", style: INFO, icon: Clock3 },
  awaiting_customer: { label: "Awaiting customer", style: WARN, icon: Clock3 },
  published: { label: "Published", style: GOOD, icon: CircleCheck },
  monitoring: { label: "Monitoring", style: GOOD, icon: CircleCheck },
  reassessment: { label: "Reassessment", style: WARN, icon: Clock3 },
  returned: { label: "Returned", style: WARN, icon: Clock3 },
  superseded: { label: "Superseded", style: NEUTRAL, icon: CircleHelp },
  withdrawn: { label: "Withdrawn", style: NEUTRAL, icon: XCircle },
  closed: { label: "Closed", style: GOOD, icon: CircleCheck },
  answered: { label: "Answered", style: GOOD, icon: CircleCheck },
  accepted: { label: "Accepted", style: GOOD, icon: CircleCheck },
  proposed: { label: "Proposed", style: INFO, icon: Clock3 },
  rejected: { label: "Rejected", style: NEUTRAL, icon: XCircle },
  // collection status
  complete: { label: "Complete collection", style: GOOD, icon: CircleCheck },
  partial: { label: "Partial collection", style: WARN, icon: Clock3 },
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const meta = STATUS[status] ?? { label: status, style: "bg-gray-100 text-gray-600", icon: CircleHelp };
  const Icon = meta.icon;
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", meta.style)}>
      <Icon className="size-3" aria-hidden />
      {label ?? meta.label}
    </span>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return <th className={clsx("px-5 py-2.5 text-left text-xs font-medium text-muted", className)}>{children}</th>;
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={clsx("px-5 py-3 align-middle text-[13px] text-ink", className)}>{children}</td>;
}

export function TableWrap({ children, minWidth = "min-w-[560px]", label = "Table" }: { children: ReactNode; minWidth?: string; label?: string }) {
  // Focusable so keyboard users can scroll wide tables on small screens.
  return (
    <div className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-brand-600" tabIndex={0} role="region" aria-label={label}>
      <table className={clsx("w-full border-t border-line", minWidth)}>{children}</table>
    </div>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="px-5 py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mt-1 text-sm text-muted">{body}</p>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {message}
    </div>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[11px] text-muted">{children}</span>;
}

export function ControlStateBadges({ result, validity }: { result: string; validity: string }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <StatusBadge status={result} />
      {validity !== "current" && validity !== "not_collected" && <StatusBadge status={validity} />}
    </span>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return <p role="status" className="py-6 text-sm text-muted">{label}</p>;
}

export function ApiErrorBanner({ error }: { error: { status?: number; code?: string; message: string } | null }) {
  if (!error) return null;
  if (error.status === 403) {
    const label = error.code === "separation_of_duties" ? "Separation of duties" : "Permission denied";
    return (
      <div role="alert" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        {label}: {error.message}
      </div>
    );
  }
  return <ErrorBanner message={error.message} />;
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "danger" | "success"; children: ReactNode }) {
  const style = { info: "border-sky-200 bg-sky-50 text-sky-800", warn: "border-amber-200 bg-amber-50 text-amber-800",
    danger: "border-red-200 bg-red-50 text-red-700", success: "border-emerald-200 bg-emerald-50 text-emerald-800" }[tone];
  return <div className={clsx("rounded-lg border px-4 py-3 text-sm", style)}>{children}</div>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputClass = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-brand-600";
