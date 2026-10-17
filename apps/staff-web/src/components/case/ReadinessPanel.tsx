"use client";

import { Card, CardHeader, EmptyState, Mono, Notice, SeverityBadge, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime, pct, shortHash, timeAgo } from "@assureops/ui/format";
import clsx from "clsx";
import { FileDiff, HeartPulse, Lock, LockOpen, CircleHelp, Radio, ShieldCheck } from "lucide-react";
import { KeyValue } from "@/components/staff-ui";
import type { Overview } from "@/lib/types";

const GATE = {
  blocked: { label: "Blocked", tone: "text-red-700", bg: "bg-red-50", icon: Lock },
  incomplete: { label: "Incomplete", tone: "text-amber-700", bg: "bg-amber-50", icon: CircleHelp },
  ready: { label: "Ready", tone: "text-brand-700", bg: "bg-brand-50", icon: LockOpen },
};

export function ReadinessPanel({ overview }: { overview: Overview }) {
  const { readiness: r, release, change, runtime, health } = overview;

  if (!release || !r) {
    return (
      <Card className="mb-5">
        <CardHeader title="Application readiness" />
        <EmptyState title="No release collected" body="The customer has not submitted a release, so there is no readiness state to assess yet." />
      </Card>
    );
  }

  const gate = GATE[r.gate.status];
  const GateIcon = gate.icon;

  return (
    <Card className="mb-5">
      <CardHeader title="Application readiness" icon={<ShieldCheck className="size-4" aria-hidden />}
        count={`${release.version} · profile ${r.profile.version} · computed ${timeAgo(r.computed_at)}`} />
      <div className="space-y-2 px-5">
        {release.collection_status === "partial" && <Notice tone="warn">Partial collection for {release.version}: {release.collection_gaps.join("; ") || "gaps not listed"}. Evidence cannot be reused until resolved.</Notice>}
      </div>

      <div className="grid gap-3 px-5 py-3 sm:grid-cols-2 xl:grid-cols-5">
        <div className={clsx("rounded-lg px-4 py-3 xl:col-span-2", gate.bg)}>
          <p className="text-xs text-muted">Release gate (policy {r.profile.gate_policy})</p>
          <p className={clsx("mt-0.5 flex items-center gap-2 text-lg font-bold", gate.tone)}><GateIcon className="size-5" aria-hidden />{gate.label}</p>
          <p className="mt-1 text-xs text-ink">{r.gate.reason}</p>
          {(r.gate.blocking.length > 0 || r.gate.incomplete.length > 0 || r.gate.warnings.length > 0) && (
            <ul className="mt-2 space-y-0.5 text-xs">
              {r.gate.blocking.map((b) => <li key={`b-${b}`} className="text-red-700">Blocking: {b}</li>)}
              {r.gate.incomplete.map((b) => <li key={`i-${b}`} className="text-amber-700">Incomplete: {b}</li>)}
              {r.gate.warnings.map((b) => <li key={`w-${b}`} className="text-muted">Warning: {b}</li>)}
            </ul>
          )}
        </div>
        <div className="rounded-lg bg-canvas px-4 py-3">
          <p className="text-xs text-muted">Evidence support</p>
          <p className="mt-0.5 text-lg font-bold">{pct(r.scores.evidence_support_pct)}</p>
          <p className="text-xs text-muted">{r.scores.controls_supported}/{r.scores.controls_total} controls supported</p>
        </div>
        <div className="rounded-lg bg-canvas px-4 py-3">
          <p className="text-xs text-muted">Evidence coverage</p>
          <p className="mt-0.5 text-lg font-bold">{pct(r.scores.evidence_coverage_pct)}</p>
          <p className="text-xs text-muted">{r.scores.controls_covered}/{r.scores.controls_total} controls with current completed evidence</p>
        </div>
        <div className="rounded-lg bg-canvas px-4 py-3">
          <p className="text-xs text-muted">Tests</p>
          <p className="mt-0.5 text-lg font-bold">{r.counts.tests_current_passing}/{r.counts.tests_total}</p>
          <p className="text-xs text-muted">current and passing · {r.counts.retest_needed} to retest · {r.counts.open_findings} open findings ({r.counts.critical_open} critical)</p>
        </div>
      </div>

      <div className="grid gap-3 px-5 pb-3 sm:grid-cols-2">
        <div className="flex items-start gap-3 rounded-lg border border-line px-4 py-3">
          <Radio className="mt-0.5 size-4 text-muted" aria-hidden />
          <div className="min-w-0 text-sm">
            <p className="text-xs text-muted">Runtime coverage</p>
            <p className="flex flex-wrap items-center gap-2"><StatusBadge status={runtime.status} /><span className="text-xs text-muted">{runtime.current}/{runtime.expected} sources current</span></p>
            {runtime.sources.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-xs text-muted">
                {runtime.sources.map((s) => (
                  <li key={s.source_id}><span className="font-mono">{s.source_id}</span> ({s.kind}) · {s.status} · last seen {timeAgo(s.last_seen)}{s.missing_sequences ? ` · ${s.missing_sequences} missing sequences` : ""}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <div className="flex items-start gap-3 rounded-lg border border-line px-4 py-3">
          <HeartPulse className="mt-0.5 size-4 text-muted" aria-hidden />
          <div className="text-sm">
            <p className="text-xs text-muted">Operational health (separate from assessment)</p>
            <p className="flex flex-wrap items-center gap-2"><StatusBadge status={health.status} />{health.latency_ms != null && <span className="text-xs text-muted">{health.latency_ms} ms</span>}</p>
            <p className="text-xs text-muted">{health.window} · {formatTime(health.checked_at)}</p>
          </div>
        </div>
      </div>

      <h3 className="px-5 pt-2 pb-2 text-sm font-semibold">Controls</h3>
      <TableWrap minWidth="min-w-[760px]">
        <thead><tr><Th>Control</Th><Th>Family</Th><Th>Control result</Th><Th>Evidence validity</Th><Th>Tests passing</Th><Th>Failure severity</Th><Th>Runtime</Th></tr></thead>
        <tbody className="divide-y divide-line">
          {r.controls.map((c) => (
            <tr key={c.id}>
              <Td><span className="font-medium">{c.id}</span> {c.name}</Td>
              <Td className="text-muted">{c.family}</Td>
              <Td><StatusBadge status={c.result} /></Td>
              <Td><StatusBadge status={c.evidence_validity} /></Td>
              <Td>{c.passed}/{c.total}</Td>
              <Td>{c.failure_severity ? <SeverityBadge severity={c.failure_severity} /> : <span className="text-muted">—</span>}</Td>
              <Td>{c.runtime_violation ? <span className="text-xs font-semibold text-red-700">Verified violation</span> : <span className="text-xs text-muted">None</span>}</Td>
            </tr>
          ))}
        </tbody>
      </TableWrap>

      <div className="border-t border-line px-5 py-4">
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold"><FileDiff className="size-4" aria-hidden />Latest change</h3>
        {!change ? <p className="text-sm text-muted">No previous release to compare against.</p> : (
          <div className="space-y-3">
            <dl className="grid gap-3 sm:grid-cols-4">
              <KeyValue label="Compared">{change.base ?? "—"} → {change.target}</KeyValue>
              <KeyValue label="Components changed">{change.changes.length}</KeyValue>
              <KeyValue label="Retest · reusable">{change.retest.length} retest · {change.reusable.length} reusable</KeyValue>
              <KeyValue label="Edge revision"><Mono>{shortHash(change.edge_revision, 12)}</Mono></KeyValue>
            </dl>
            {(change.partial_collection || change.conservative_fallback || change.unmapped.length > 0) && (
              <Notice tone="warn">
                {change.partial_collection && "Partial collection. "}
                {change.conservative_fallback && "Conservative fallback applied: unmapped changes force a retest. "}
                {change.unmapped.length > 0 && `Unmapped components: ${change.unmapped.join(", ")}.`}
              </Notice>
            )}
            {change.changes.length > 0 && (
              <ul className="divide-y divide-line rounded-lg border border-line text-[13px]">
                {change.changes.map((c) => (
                  <li key={c.component} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                    <span><span className="capitalize">{c.change}</span> <span className="font-mono text-xs">{c.component}</span> <span className="text-muted">· {c.label}</span></span>
                    <span className="flex items-center gap-2 text-xs text-muted">
                      {c.affected_controls.length ? `affects ${c.affected_controls.join(", ")}` : c.impact === "unknown" ? "unmapped" : "no mapped evidence"}
                      <SeverityBadge severity={c.impact} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      <p className="border-t border-line px-5 py-3 text-xs text-muted">
        Control result, evidence validity, runtime coverage, health and gate are separate dimensions. Readiness applies within the tested boundary; it is not a certification.
      </p>
    </Card>
  );
}
