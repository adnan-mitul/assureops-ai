"use client";

import { usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Card, EmptyState, inputClass, LoadingState, Mono, SeverityBadge, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import clsx from "clsx";
import { Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { PageTop, WithSuspense } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { Finding } from "@/lib/types";

const STATES = [["all", "All"], ["open", "Open"], ["under_review", "Under review"], ["reopened", "Reopened"], ["resolved", "Resolved"]] as const;

function FindingsView() {
  const { applicationId } = useApp();
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const q = params.get("q") ?? "";
  const state = params.get("state") ?? "all";
  const severity = params.get("severity") ?? "all";
  const source = params.get("source") ?? "all";
  const control = params.get("control") ?? "all";
  const [draft, setDraft] = useState(q);
  const [lastQ, setLastQ] = useState(q);
  if (q !== lastQ) {
    setLastQ(q);
    setDraft(q);
  }
  const { data, error, loading } = usePoll<Finding[]>(applicationId ? `/v1/findings?application_id=${encodeURIComponent(applicationId)}` : null, 5000);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (!value || value === "all") next.delete(key);
    else next.set(key, value);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setParam("q", draft.trim());
  };

  if (!applicationId || (loading && !data)) return <LoadingState label="Loading findings…" />;
  if (!data) return <ApiErrorBanner error={error} />;

  const needle = q.toLowerCase();
  const rows = data.filter((f) => (state === "all" || f.state === state) && (severity === "all" || f.severity === severity)
    && (source === "all" || f.source === source) && (control === "all" || f.control === control)
    && (!needle || [f.title, f.description, f.control, f.control_name, f.test_id ?? "", f.id].some((v) => v.toLowerCase().includes(needle))));
  const controls = [...new Map(data.map((f) => [f.control, f.control_name])).entries()].sort();
  const count = (s: string) => (s === "all" ? data.length : data.filter((f) => f.state === s).length);

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Findings" title="Findings" subtitle="A finding comes from a failed test or a verified runtime violation. It resolves only through passing retest evidence or a staff reviewer determination." />
      <ApiErrorBanner error={error} />
      <Card>
        <div className="flex flex-col gap-3 border-b border-line px-5 py-4">
          <nav className="flex flex-wrap gap-1 text-sm" aria-label="Filter by state">
            {STATES.map(([value, label]) => (
              <button key={value} type="button" onClick={() => setParam("state", value)} aria-pressed={state === value}
                className={clsx("rounded-md px-3 py-1.5", state === value ? "bg-brand-50 font-semibold text-brand-700" : "text-gray-600 hover:bg-canvas")}>
                {label} <span className="text-xs text-muted">{count(value)}</span>
              </button>
            ))}
          </nav>
          <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto_auto]">
            <form role="search" onSubmit={submit} className="relative">
              <label htmlFor="findings-search" className="sr-only">Search findings</label>
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
              <input id="findings-search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Search title, control, test…" className={clsx(inputClass, "pl-9")} />
            </form>
            <select value={severity} onChange={(e) => setParam("severity", e.target.value)} className={inputClass} aria-label="Severity">
              <option value="all">All severities</option>
              {["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select value={control} onChange={(e) => setParam("control", e.target.value)} className={inputClass} aria-label="Control">
              <option value="all">All controls</option>
              {controls.map(([id, name]) => <option key={id} value={id}>{id} {name}</option>)}
            </select>
            <select value={source} onChange={(e) => setParam("source", e.target.value)} className={inputClass} aria-label="Source">
              <option value="all">All sources</option>
              <option value="test">Assessment test</option>
              <option value="runtime">Verified runtime violation</option>
            </select>
          </div>
          {q && <p className="text-xs text-muted">Showing matches for “{q}”. <button type="button" className="underline" onClick={() => setParam("q", "")}>Clear search</button></p>}
        </div>
        {rows.length === 0 ? (
          <EmptyState title={data.length ? "No findings match these filters" : "No findings yet"} body={data.length ? "Change the state, severity, control, source or search." : "Findings appear when a test fails or a verified runtime violation contradicts a control."} />
        ) : (
          <TableWrap minWidth="min-w-[820px]">
            <thead><tr><Th>Severity</Th><Th>Control</Th><Th>Finding</Th><Th>Source</Th><Th>State</Th><Th>Releases</Th><Th>Updated</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {rows.map((f) => (
                <tr key={f.id}>
                  <Td><SeverityBadge severity={f.severity} /></Td>
                  <Td className="whitespace-nowrap">{f.control} {f.control_name}</Td>
                  <Td><Link href={`/findings/${f.id}`} className="font-medium hover:underline">{f.title}</Link><span className="block"><Mono>{f.id}</Mono></span></Td>
                  <Td className="text-xs">{f.source === "runtime" ? "Verified runtime violation" : <>Test <span className="font-mono">{f.test_id}</span></>}</Td>
                  <Td><StatusBadge status={f.state} /></Td>
                  <Td className="whitespace-nowrap text-xs">{f.first_release === f.last_release ? f.first_release ?? "—" : `${f.first_release ?? "—"} → ${f.last_release ?? "—"}`}</Td>
                  <Td className="whitespace-nowrap text-muted">{formatTime(f.updated_at)}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
    </div>
  );
}

export default function FindingsPage() {
  return <WithSuspense label="Loading findings…"><FindingsView /></WithSuspense>;
}
