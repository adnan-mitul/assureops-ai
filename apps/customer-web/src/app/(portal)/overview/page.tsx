"use client";

import { usePoll } from "@assureops/ui/client";
import { colorFor, ControlDonut, RESULT_COLORS, TrendChart } from "@assureops/ui/charts";
import {
  ApiErrorBanner, Button, Card, CardHeader, ControlStateBadges, EmptyState, LoadingState, Mono, Notice, SeverityBadge, StatusBadge, TableWrap, Td, Th, ViewAll,
} from "@assureops/ui/components";
import { EvidenceDrawer } from "@assureops/ui/evidence-drawer";
import { formatTime, pct, shortHash, timeAgo } from "@assureops/ui/format";
import clsx from "clsx";
import {
  ArrowRight, Bot, CircleAlert, CircleCheck, CircleDashed, CircleHelp, CircleX, ClipboardList, FileDiff, HeartPulse, Lock, LockOpen, RefreshCw, ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ReleaseActions } from "@/components/ReleaseActions";
import { useApp } from "@/lib/app-context";
import type { Overview } from "@/lib/types";

const GATE_STYLE = {
  blocked: { label: "Blocked", tone: "text-red-600", bg: "bg-red-50 text-red-600", icon: Lock },
  incomplete: { label: "Incomplete", tone: "text-amber-600", bg: "bg-amber-50 text-amber-600", icon: CircleHelp },
  ready: { label: "Ready", tone: "text-brand-700", bg: "bg-brand-50 text-brand-700", icon: LockOpen },
};

export default function OverviewPage() {
  const { applicationId } = useApp();
  const { data, error, loading, refresh } = usePoll<Overview>(applicationId ? `/v1/applications/${applicationId}/overview` : null, 3000);
  const [drawer, setDrawer] = useState<string | null>(null);

  if (!applicationId || (loading && !data)) return <LoadingState label="Loading readiness…" />;
  if (!data) return <ApiErrorBanner error={error} />;

  const running = data.assessment?.running;
  const header = (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="text-sm font-medium text-muted">Dashboard</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">AI Application Readiness</h1>
        <p className="mt-1 text-sm text-muted">Continuous assurance for your AI applications</p>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex items-start gap-2 text-xs">
          <span className={clsx("mt-1 size-2 rounded-full", running ? "animate-pulse bg-amber-500" : "bg-brand-500")} aria-hidden />
          <div>
            <p className="text-muted">{running ? `Assessment ${running.status}` : "Last computed"}</p>
            <p className="font-medium">{formatTime(data.readiness?.computed_at)}</p>
          </div>
        </div>
        <Button onClick={refresh}><RefreshCw className="size-4" aria-hidden /> Refresh</Button>
      </div>
    </div>
  );

  if (!data.release || !data.readiness) {
    return (
      <div className="mx-auto max-w-[1400px]">
        {header}
        <Card>
          {data.onboarding && !data.onboarding.steps.slice(0, 3).every((s) => s.done) ? (
            <>
              <EmptyState title="Finish connecting this application" body={`Next: ${data.onboarding.steps.find((s) => !s.done)?.label ?? ""}. Releases can be collected once the connection is verified and a reviewed profile is active.`} />
              <div className="flex justify-center pb-8"><Link href={`/applications/${encodeURIComponent(applicationId)}/connect`}
                className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-3.5 py-2 text-sm font-medium text-white hover:bg-brand-800">Open connection setup</Link></div>
            </>
          ) : (
            <>
              <EmptyState title="No release submitted yet" body="Submit the running release to collect its manifest, then run a full assessment." />
              <div className="flex justify-center pb-8"><ReleaseActions applicationId={applicationId} running={!!running} onChange={refresh} /></div>
            </>
          )}
        </Card>
      </div>
    );
  }

  const { readiness: r, release, change, findings = [], trend = [] } = data;
  const gate = GATE_STYLE[r.gate.status];
  const GateIcon = gate.icon;
  const retests = r.tests.filter((t) => t.validity !== "current" || t.result === "failed" || t.result === "unverified");
  const lastJob = data.assessment?.last;

  return (
    <div className="mx-auto max-w-[1400px]">
      {header}
      <div className="mb-4 space-y-2">
        <ApiErrorBanner error={error} />
        {lastJob?.status === "failed" && <Notice tone="danger">Last assessment failed: {lastJob.error}</Notice>}
        {release.collection_status === "partial" && <Notice tone="warn">Partial collection for {release.version}: {release.collection_gaps.join("; ")}. Evidence cannot be reused until the gaps are resolved.</Notice>}
        {running && <Notice tone="info">Assessment {running.id} is {running.status}: {running.steps.filter((s) => s.status === "done").length}/{running.steps.length} steps done. <Link className="underline" href={`/assessments/${running.id}`}>Follow progress</Link></Notice>}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-5">
          <div className="flex items-start gap-4">
            <span className="grid size-11 place-items-center rounded-full bg-brand-50 text-brand-700"><ShieldCheck className="size-5" aria-hidden /></span>
            <div>
              <p className="text-sm font-medium">Evidence Support</p>
              <p className="mt-1 text-3xl font-bold">{pct(r.scores.evidence_support_pct)}</p>
            </div>
          </div>
          <div className="mt-4 h-2 rounded-full bg-gray-100" role="progressbar" aria-label="Evidence support" aria-valuenow={r.scores.evidence_support_pct ?? 0} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-2 rounded-full bg-brand-600" style={{ width: `${r.scores.evidence_support_pct ?? 0}%` }} />
          </div>
          <p className="mt-2 text-xs text-muted">{r.scores.controls_supported}/{r.scores.controls_total} controls supported · coverage {pct(r.scores.evidence_coverage_pct)}
            {r.scores.controls_unassessed ? ` · ${r.scores.controls_unassessed} not assessed by this profile` : ""}</p>
        </Card>

        <Card className="p-5">
          <div className="flex items-start gap-4">
            <span className="grid size-11 place-items-center rounded-full bg-red-50 text-red-600"><CircleAlert className="size-5" aria-hidden /></span>
            <div>
              <p className="text-sm font-medium">Critical Findings</p>
              <p className={clsx("mt-1 text-3xl font-bold", r.counts.critical_open > 0 && "text-red-600")}>{r.counts.critical_open}</p>
            </div>
          </div>
          <p className="mt-5 text-xs text-muted">{r.counts.critical_open ? "Requires immediate attention" : "No open critical findings"} · {r.counts.open_findings} open in total</p>
        </Card>

        <Card className="p-5">
          <div className="flex items-start gap-4">
            <span className="grid size-11 place-items-center rounded-full bg-sky-50 text-sky-600"><RefreshCw className="size-5" aria-hidden /></span>
            <div>
              <p className="text-sm font-medium">Tests to Retest</p>
              <p className="mt-1 text-3xl font-bold">{r.counts.retest_needed}</p>
            </div>
          </div>
          <p className="mt-5 text-xs text-muted">Out of {r.counts.tests_total} tests{change ? ` · ${change.reusable.length} reusable after ${change.base} → ${change.target}` : ""}</p>
        </Card>

        <Card className="p-5">
          <div className="flex items-start gap-4">
            <span className={clsx("grid size-11 place-items-center rounded-full", gate.bg)}><GateIcon className="size-5" aria-hidden /></span>
            <div>
              <p className="text-sm font-medium">Release Gate</p>
              <p className={clsx("mt-1 text-2xl font-bold", gate.tone)}>{gate.label}</p>
            </div>
          </div>
          <p className="mt-4 line-clamp-2 text-xs text-muted">{r.gate.reason}</p>
        </Card>
      </div>

      <Card className="mt-5">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-5 py-4">
          <div className="flex items-center gap-4">
            <span className="grid size-11 place-items-center rounded-lg bg-gray-900 text-white"><Bot className="size-5" aria-hidden /></span>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold">{data.application.name}</h2>
                <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700 capitalize">{data.application.environment}</span>
                <span className="rounded-full bg-canvas px-2 py-0.5 text-xs text-muted">{data.application.mode.replaceAll("_", " ")}</span>
              </div>
              <p className="text-sm text-muted">{data.application.description}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-6 text-sm">
            <div><p className="text-xs text-muted">Release</p><p className="font-semibold">{release.version} <Mono>#{release.manifest_hash}</Mono></p></div>
            <div><p className="text-xs text-muted">Collected</p><p className="font-semibold">{formatTime(release.created_at)}</p></div>
            <div><p className="text-xs text-muted">Profile</p><p className="font-semibold">{r.profile.version}</p></div>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
          <nav className="flex flex-wrap gap-1 text-sm" aria-label="Application sections">
            {[["Overview", "/overview"], ["Findings", "/findings"], ["Evidence", "/evidence"], ["Changes", change?.id ? `/changes/${change.id}` : "/releases"],
              ["Retests", "/assessments"], ["Incidents", "/monitoring"], ["Releases", "/releases"]].map(([label, href]) => (
              <Link key={label} href={href} className={clsx("rounded-md px-3 py-1.5", label === "Overview" ? "bg-brand-50 font-semibold text-brand-700" : "text-gray-600 hover:bg-canvas")}>{label}</Link>
            ))}
          </nav>
          <ReleaseActions applicationId={applicationId} changeId={change?.id} running={!!running} onChange={refresh} />
        </div>

        <div className="grid gap-4 px-5 pb-2 sm:grid-cols-3">
          <div className="flex items-center gap-3 rounded-lg bg-canvas px-4 py-3">
            <HeartPulse className="size-5 text-muted" aria-hidden />
            <div className="text-sm"><p className="text-xs text-muted">Operational health</p>
              <p className="flex items-center gap-2"><StatusBadge status={data.health.status} />{data.health.latency_ms != null && <span className="text-xs text-muted">{data.health.latency_ms} ms probe</span>}</p></div>
          </div>
          <div className="flex items-center gap-3 rounded-lg bg-canvas px-4 py-3">
            <ClipboardList className="size-5 text-muted" aria-hidden />
            <div className="text-sm"><p className="text-xs text-muted">Assessment coverage</p><p>{r.scores.controls_covered}/{r.scores.controls_total} controls with current completed evidence</p></div>
          </div>
          <div className="flex items-center gap-3 rounded-lg bg-canvas px-4 py-3">
            <ShieldCheck className="size-5 text-muted" aria-hidden />
            <div className="text-sm"><p className="text-xs text-muted">Runtime coverage</p>
              <p className="flex items-center gap-2"><StatusBadge status={data.runtime.status} /><span className="text-xs text-muted">{data.runtime.current}/{data.runtime.expected} sources current</span></p></div>
          </div>
        </div>

        <div className="grid gap-4 p-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div className="rounded-xl border border-line p-4">
            <h3 className="mb-2 text-sm font-semibold">Readiness Trend</h3>
            <TrendChart points={trend.map((p, i) => ({ label: `${p.release} #${i + 1}`, support: p.evidence_support, coverage: p.evidence_coverage }))} />
            <p className="mt-1 text-xs text-muted">Each point is a completed assessment. Evidence support is not a probability of safety.</p>
          </div>
          <div className="rounded-xl border border-line p-4">
            <h3 className="mb-2 text-sm font-semibold">Control Families</h3>
            <div className="flex flex-wrap items-center gap-6">
              <ControlDonut controls={r.controls} />
              <ul className="min-w-56 flex-1 space-y-1.5 text-[13px]">
                {r.controls.map((c) => (
                  <li key={c.id} className="flex items-center justify-between gap-3" title={`${c.id} · ${c.family}`}>
                    <span className="flex items-center gap-2"><span className="size-2.5 rounded-sm" style={{ background: colorFor(c) }} aria-hidden />{c.name}</span>
                    <span className="flex items-center gap-2 text-muted"><span className="sr-only">{c.result}, {c.evidence_validity}</span>{c.result === "unassessed" ? "not assessed" : c.result === "not_applicable" ? "not applicable" : `${c.passed}/${c.total}`}</span>
                  </li>
                ))}
              </ul>
            </div>
            <p className="mt-3 flex flex-wrap gap-3 text-xs text-muted">
              {Object.entries(RESULT_COLORS).map(([k, v]) => <span key={k} className="flex items-center gap-1"><span className="size-2 rounded-sm" style={{ background: v }} />{k.replace("_", " ")}</span>)}
            </p>
          </div>
        </div>
      </Card>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Recent Findings" action={<ViewAll href="/findings" />} />
          {findings.length === 0 ? <EmptyState title="No findings yet" body="Findings appear when a test fails or a verified runtime violation contradicts a control." /> : (
            <TableWrap>
              <thead><tr><Th>Severity</Th><Th>Control</Th><Th>Finding</Th><Th>Status</Th><Th>Updated</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {findings.slice(0, 5).map((f) => (
                  <tr key={f.id}>
                    <Td><SeverityBadge severity={f.severity} /></Td>
                    <Td className="whitespace-nowrap">{f.control_name}</Td>
                    <Td><Link href={`/findings/${f.id}`} className="hover:underline">{f.title}</Link><div className="text-xs text-muted">{f.source === "runtime" ? "Verified in operation" : `Test ${f.test_id}`}</div></Td>
                    <Td><StatusBadge status={f.state} /></Td>
                    <Td className="whitespace-nowrap text-muted">{formatTime(f.updated_at)}</Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )}
        </Card>

        <Card>
          <CardHeader title="Recent Changes" icon={<FileDiff className="size-4" aria-hidden />} count={change ? `${change.base ?? "—"} → ${change.target}` : undefined}
            action={change?.id ? <ViewAll href={`/changes/${change.id}`} label="Details" /> : <ViewAll href="/releases" />} />
          {!change || change.changes.length === 0 ? <EmptyState title="No changes to compare" body="Changes appear after a newer release is submitted." /> : (
            <TableWrap minWidth="min-w-0">
              <thead><tr><Th>Type</Th><Th>Summary</Th><Th>Impact</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {change.changes.map((c) => (
                  <tr key={c.component}>
                    <Td><p>{c.label}</p><Mono>{shortHash(c.after ?? c.before)}</Mono></Td>
                    <Td><p className="capitalize">{c.change} <span className="font-mono text-xs">{c.component}</span></p>
                      <p className="text-xs text-muted">{c.affected_controls.length ? `Invalidates evidence for ${c.affected_controls.join(", ")}` : c.impact === "unknown" ? "Unmapped: conservative retest" : "No mapped evidence affected"}</p></Td>
                    <Td><SeverityBadge severity={c.impact} /></Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )}
        </Card>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Retests Required" icon={<ClipboardList className="size-4" aria-hidden />} count={`${retests.length} tests`} action={<ViewAll href="/assessments" />} />
          {retests.length === 0 ? <EmptyState title="Nothing to retest" body="All evidence is current for this release." /> : (
            <TableWrap>
              <thead><tr><Th>Test</Th><Th>Control</Th><Th>Reason</Th><Th>Priority</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {retests.map((t) => {
                  const plan = change?.retest.find((x) => x.test_id === t.test_id);
                  const reason = t.result === "failed" ? `Failing on ${t.release} — fix and retest`
                    : t.validity === "stale" ? `Evidence stale: ${plan?.reasons.filter((x) => x.includes(":")).join(", ") || "dependency or freshness"}`
                    : t.validity === "unavailable" && t.run_id ? "Evidence unavailable" : "Never verified";
                  return (
                    <tr key={t.test_id}>
                      <Td><p>{t.name}</p><Mono>{t.test_id}</Mono></Td>
                      <Td className="whitespace-nowrap">{r.controls.find((c) => c.id === t.control)?.name}</Td>
                      <Td className="text-muted">{reason}</Td>
                      <Td><SeverityBadge severity={t.severity} /></Td>
                    </tr>
                  );
                })}
              </tbody>
            </TableWrap>
          )}
        </Card>

        <Card className="p-5">
          <div className="flex items-start gap-3">
            <GateIcon className={clsx("mt-0.5 size-5", gate.tone)} aria-hidden />
            <div>
              <h2 className="text-[15px] font-semibold">Release Gate · {release.version}</h2>
              <p className={clsx("text-xl font-bold", gate.tone)}>{gate.label}</p>
              <p className="mt-1 text-xs text-muted">{r.gate.reason}</p>
            </div>
          </div>
          <ul className="mt-4 space-y-2.5 text-sm">
            {r.controls.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2">
                  {c.result === "failed" ? <CircleX className="size-4 text-red-600" aria-hidden /> : c.result === "supported" && c.evidence_validity === "current"
                    ? <CircleCheck className="size-4 text-brand-600" aria-hidden /> : c.result === "unassessed" || c.result === "not_applicable"
                      ? <CircleDashed className="size-4 text-gray-400" aria-hidden /> : <CircleAlert className="size-4 text-amber-500" aria-hidden />}
                  <span>
                    {c.id} {c.name}
                    {c.applicability && (
                      <span className="block text-xs text-muted">{c.applicability.reviewed ? c.applicability.reason : "No reviewed applicability reason recorded"}</span>
                    )}
                  </span>
                </span>
                <ControlStateBadges result={c.result} validity={c.evidence_validity} />
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">Gate policy {r.profile.gate_policy}: critical and high failures block; stale, unverified or unreviewed evidence makes the release incomplete.</p>
          {data.publication && <p className="mt-2 text-xs text-muted">Latest published report: {data.publication.release} · {timeAgo(data.publication.at)} · <Link className="underline" href={`/reports/${data.publication.report_id}`}>open</Link></p>}
          <Link href="/releases" className="mt-5 flex items-center justify-center gap-2 rounded-lg bg-brand-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-800">
            View release details <ArrowRight className="size-4" aria-hidden />
          </Link>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader title="Test evidence for this release" count={`${r.counts.tests_current_passing}/${r.counts.tests_total} current and passing`} action={<ViewAll href="/evidence" />} />
        <TableWrap>
          <thead><tr><Th>Test</Th><Th>Control</Th><Th>Result</Th><Th>Evidence</Th><Th>From</Th><Th /></tr></thead>
          <tbody className="divide-y divide-line">
            {r.tests.map((t) => (
              <tr key={t.test_id}>
                <Td><p>{t.name}</p><Mono>{t.test_id}</Mono></Td>
                <Td>{t.control}</Td>
                <Td><StatusBadge status={t.result} /></Td>
                <Td><StatusBadge status={t.reused ? "reused" : t.validity} /></Td>
                <Td className="text-muted">{t.release ?? "—"}</Td>
                <Td>{t.run_id && <button className="text-xs font-medium text-brand-700 hover:underline" onClick={() => setDrawer(t.run_id!)}>Open evidence</button>}</Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      </Card>
      {drawer && <EvidenceDrawer runId={drawer} onClose={() => setDrawer(null)} />}
    </div>
  );
}
