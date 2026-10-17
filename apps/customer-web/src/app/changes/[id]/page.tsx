"use client";

import { newIdempotencyKey, post, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, LoadingState, Mono, Notice, SeverityBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime, shortHash } from "@assureops/ui/format";
import { ClipboardList, FileDiff, Loader2, Recycle, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Fact, PageTop, useRouteId, WithSuspense } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { AssessmentCreated, ChangeSet } from "@/lib/types";

function ChangeView() {
  const id = useRouteId();
  const { canWrite, applicationId } = useApp();
  const router = useRouter();
  const { data, error, loading } = usePoll<ChangeSet>(`/v1/changes/${encodeURIComponent(id)}`, 0);
  const { busy, error: actionError, run } = useAction();
  const [key] = useState(newIdempotencyKey);

  if (loading && !data) return <LoadingState label="Loading change set…" />;
  if (!data) return <ApiErrorBanner error={error} />;

  const requestRetest = () => run("retest", async () => {
    const job = await post<AssessmentCreated>(`/v1/changes/${encodeURIComponent(id)}/retests`, {}, key);
    router.push(`/assessments/${job.id}`);
  });

  const releasesHref = applicationId ? `/applications/${encodeURIComponent(applicationId)}/releases` : "/releases";

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Changes" title={`${data.base ?? "No prior release"} → ${data.target}`}
        subtitle="What changed between two exact releases, which evidence that invalidates, and the minimum retest plan."
        actions={canWrite ? (
          <Button variant="primary" disabled={!!busy} onClick={requestRetest}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <RefreshCw className="size-4" aria-hidden />} Request retest
          </Button>
        ) : <p className="text-xs text-muted">Your role can view change sets but cannot request retests.</p>} />

      <div className="mb-4 space-y-2">
        {actionError && <div role="alert"><Notice tone="danger">{actionError}{actionError.includes("newer release") && <> <Link className="underline" href={releasesHref}>Compare against the latest release</Link></>}</Notice></div>}
        {data.base === null && <Notice tone="info">There is no earlier release to compare with, so every test in the profile is planned and nothing is reused.</Notice>}
        {data.partial_collection && <Notice tone="warn">Partial collection on {data.target}: evidence reuse is not allowed until the manifest gaps are resolved, so every test is retested.</Notice>}
        {data.conservative_fallback && data.base !== null && (
          <Notice tone="warn">Conservative fallback applied{data.unmapped.length ? `: ${data.unmapped.length} changed component(s) have no reviewed dependency mapping, so they are assumed to affect every test` : ""}.</Notice>
        )}
      </div>

      <Card className="p-5">
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <Fact label="Change set"><Mono>{data.id}</Mono></Fact>
          <Fact label="Retest plan id"><Mono>{data.plan_id ?? "—"}</Mono></Fact>
          <Fact label="Dependency edge revision"><Mono>{shortHash(data.edge_revision, 16)}</Mono></Fact>
          <Fact label="Created">{formatTime(data.created_at)}</Fact>
          <Fact label="Created by">{data.created_by ?? "—"}</Fact>
        </dl>
      </Card>

      <Card className="mt-5">
        <CardHeader title="Changed components" icon={<FileDiff className="size-4" aria-hidden />} count={`${data.changes.length}`} />
        {data.changes.length === 0 ? <EmptyState title="No component changes" body={data.base ? "Both releases have identical component fingerprints." : "There is no base release to diff against."} /> : (
          <TableWrap minWidth="min-w-[860px]">
            <thead><tr><Th>Component</Th><Th>Change</Th><Th>Before</Th><Th>After</Th><Th>Impact</Th><Th>Affected tests</Th><Th>Affected controls</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {data.changes.map((c) => (
                <tr key={c.component}>
                  <Td><p>{c.label}</p><span className="font-mono text-[11px] text-muted">{c.component}</span><span className="block text-xs text-muted">{c.type}</span></Td>
                  <Td className="capitalize">{c.change}</Td>
                  <Td><Mono>{c.before ? shortHash(c.before, 12) : "absent"}</Mono></Td>
                  <Td><Mono>{c.after ? shortHash(c.after, 12) : "absent"}</Mono></Td>
                  <Td><SeverityBadge severity={c.impact} />
                    <span className="block pt-1 text-xs text-muted">{c.impact === "unknown" ? "Unmapped: conservative retest" : c.impact === "none" ? "No mapped evidence affected" : "Highest affected test severity"}</span></Td>
                  <Td className="font-mono text-xs">{c.affected_tests.join(", ") || "—"}</Td>
                  <Td>{c.affected_controls.join(", ") || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
        {data.unmapped.length > 0 && (
          <div className="border-t border-line px-5 py-3 text-sm">
            <p className="text-xs font-medium text-muted">Unmapped components (no reviewed dependency edge)</p>
            <ul className="mt-1 flex flex-wrap gap-1.5">{data.unmapped.map((u) => <li key={u} className="rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 font-mono text-[11px] text-amber-800">{u}</li>)}</ul>
          </div>
        )}
      </Card>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Retest plan" icon={<ClipboardList className="size-4" aria-hidden />} count={`${data.retest.length} tests`} />
          {data.retest.length === 0 ? <EmptyState title="Nothing to retest" body="No planned test depends on a changed component." /> : (
            <TableWrap minWidth="min-w-[480px]">
              <thead><tr><Th>Test</Th><Th>Control</Th><Th>Why it must run</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.retest.map((t) => (
                  <tr key={t.test_id}>
                    <Td className="font-mono text-xs">{t.test_id}</Td>
                    <Td>{t.control}</Td>
                    <Td><ul className="space-y-0.5 text-xs">{t.reasons.map((r) => <li key={r}>{/\s/.test(r) ? r : `changed dependency ${r}`}</li>)}</ul></Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )}
        </Card>

        <Card>
          <CardHeader title="Evidence reuse" icon={<Recycle className="size-4" aria-hidden />} count={`${data.reusable.length} tests`} />
          {data.reusable.length === 0 ? <EmptyState title="No evidence reused" body="Every test in the plan must produce new evidence for this release." /> : (
            <div className="px-5 pb-5">
              <p className="text-xs text-muted">Reusable because none of the test&apos;s reviewed dependencies changed, no change is unmapped, the collection is complete and the test is not a mandatory boundary check. Earlier evidence still has to be current (same profile, within freshness) when the gate is computed.</p>
              <ul className="mt-3 flex flex-wrap gap-1.5">{data.reusable.map((t) => <li key={t} className="rounded-md bg-sky-50 px-2 py-0.5 font-mono text-[11px] text-sky-700">{t}</li>)}</ul>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

export default function ChangePage() {
  return <WithSuspense label="Loading change set…"><ChangeView /></WithSuspense>;
}
