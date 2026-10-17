"use client";

import { post, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, Field, inputClass, LoadingState, Mono, Notice, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime, shortHash } from "@assureops/ui/format";
import clsx from "clsx";
import { FileDiff, GitCompare, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { PageTop, useRouteId, WithSuspense } from "@/components/bits";
import { ReleaseActions } from "@/components/ReleaseActions";
import { useApp } from "@/lib/app-context";
import type { AssessmentJob, ChangeSet, ReleaseInfo } from "@/lib/types";

function CollectionPill({ status }: { status: ReleaseInfo["collection_status"] }) {
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", status === "complete" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700")}>
      {status === "complete" ? "Complete collection" : "Partial collection"}
    </span>
  );
}

function Compare({ applicationId, releases }: { applicationId: string; releases: ReleaseInfo[] }) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [target, setTarget] = useState(releases[0]?.id ?? "");
  const [base, setBase] = useState(releases[1]?.id ?? "");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run("compare", async () => {
      const change = await post<ChangeSet>("/v1/changes/compare", { application_id: applicationId, target_release_id: target, base_release_id: base || null });
      router.push(`/changes/${change.id}`);
    });
  };

  return (
    <form onSubmit={submit} className="grid gap-3 px-5 pb-5 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
      <Field label="Base release (before)">
        <select className={inputClass} value={base} onChange={(e) => setBase(e.target.value)}>
          <option value="">Previous release of the target</option>
          {releases.map((r) => <option key={r.id} value={r.id}>{r.version} · #{r.manifest_hash} · {formatTime(r.created_at)}</option>)}
        </select>
      </Field>
      <Field label="Target release (after)">
        <select className={inputClass} value={target} onChange={(e) => setTarget(e.target.value)} required>
          {releases.map((r) => <option key={r.id} value={r.id}>{r.version} · #{r.manifest_hash} · {formatTime(r.created_at)}</option>)}
        </select>
      </Field>
      <Button type="submit" variant="primary" disabled={!!busy || !target || base === target}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <GitCompare className="size-4" aria-hidden />} Compare
      </Button>
      {base && base === target && <p className="text-xs text-muted sm:col-span-3">Choose two different releases.</p>}
      {error && <p role="alert" className="text-xs text-red-700 sm:col-span-3">{error}</p>}
    </form>
  );
}

function ReleasesView() {
  const id = useRouteId();
  const { applications } = useApp();
  const app = applications.find((a) => a.id === id);
  const releases = usePoll<ReleaseInfo[]>(`/v1/applications/${encodeURIComponent(id)}/releases`, 10000);
  const changes = usePoll<ChangeSet[]>(`/v1/changes?application_id=${encodeURIComponent(id)}`, 10000);
  const jobs = usePoll<AssessmentJob[]>(`/v1/assessments?application_id=${encodeURIComponent(id)}`, 5000);

  if (releases.loading && !releases.data) return <LoadingState label="Loading releases…" />;
  if (!releases.data) return <ApiErrorBanner error={releases.error} />;

  const list = releases.data;
  const latest = list[0];
  const running = jobs.data?.find((j) => j.status === "queued" || j.status === "running");
  const latestChange = changes.data?.find((c) => c.target === latest?.version);
  const refresh = () => { releases.refresh(); changes.refresh(); jobs.refresh(); };

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow={app ? `Applications · ${app.name}` : "Applications"} title="Releases"
        subtitle="Every release is an immutable manifest of the exact components that were running when it was collected."
        actions={<ReleaseActions applicationId={id} changeId={latestChange?.id} running={!!running} onChange={refresh} />} />
      <div className="mb-4 space-y-2">
        <ApiErrorBanner error={releases.error ?? changes.error} />
        {running && <Notice tone="info">Assessment {running.id} is {running.status}. New assessments can start after it finishes. <Link className="underline" href={`/assessments/${running.id}`}>Follow progress</Link></Notice>}
      </div>

      {list.length === 0 ? (
        <Card><EmptyState title="No releases collected" body="Submit the running release to record its manifest." /></Card>
      ) : (
        <>
          <Card>
            <CardHeader title="Compare releases" icon={<GitCompare className="size-4" aria-hidden />} />
            <p className="-mt-1 px-5 pb-3 text-xs text-muted">Builds a change set: which components changed, which evidence they invalidate, and the retest plan.</p>
            <Compare applicationId={id} releases={list} />
          </Card>

          <div className="mt-5 space-y-4">
            {list.map((r, i) => {
              const comps = Object.entries(r.components);
              return (
                <Card key={r.id}>
                  <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-lg font-semibold">{r.version}</h2>
                        <Mono>#{r.manifest_hash}</Mono>
                        <CollectionPill status={r.collection_status} />
                        {i === 0 && <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">Latest</span>}
                      </div>
                      <p className="mt-1 text-xs text-muted">Collected {formatTime(r.created_at)} · release id <span className="font-mono">{r.id}</span></p>
                    </div>
                    <dl className="flex flex-wrap gap-6 text-sm">
                      <div><dt className="text-xs text-muted">Adapter</dt><dd className="font-medium">{r.integration.adapter ?? "—"}</dd></div>
                      <div><dt className="text-xs text-muted">MCP protocol</dt><dd className="font-medium">{r.integration.mcp_protocol_version ?? "Not reported"}</dd></div>
                      <div><dt className="text-xs text-muted">Components</dt><dd className="font-medium">{comps.length}</dd></div>
                    </dl>
                  </div>
                  {r.collection_status === "partial" && (
                    <div className="px-5 pb-3">
                      <Notice tone="warn">Partial collection. Gaps: {r.collection_gaps.join("; ") || "not specified"}. Evidence for this release cannot be reused until the gaps are resolved.</Notice>
                    </div>
                  )}
                  <div className="px-5 pb-3">
                    <p className="text-xs text-muted">Policy versions</p>
                    <ul className="mt-1 flex flex-wrap gap-1.5">
                      {Object.entries(r.policy_versions).map(([k, v]) => <li key={k} className="rounded-md border border-line px-2 py-0.5 text-xs"><span className="text-muted">{k}</span> {v}</li>)}
                      {Object.keys(r.policy_versions).length === 0 && <li className="text-xs text-muted">None reported</li>}
                    </ul>
                  </div>
                  <details className="group border-t border-line" open={i === 0}>
                    <summary className="cursor-pointer px-5 py-3 text-sm font-medium text-brand-700 hover:bg-canvas">Component fingerprints ({comps.length})</summary>
                    <TableWrap minWidth="min-w-[480px]">
                      <thead><tr><Th>Component</Th><Th>Type</Th><Th>Fingerprint</Th></tr></thead>
                      <tbody className="divide-y divide-line">
                        {comps.map(([cid, c]) => (
                          <tr key={cid}><Td className="font-mono text-xs">{cid}</Td><Td>{c.type}</Td><Td><Mono>{shortHash(c.fingerprint, 16)}</Mono></Td></tr>
                        ))}
                      </tbody>
                    </TableWrap>
                  </details>
                </Card>
              );
            })}
          </div>
        </>
      )}

      <Card className="mt-5">
        <CardHeader title="Change sets" icon={<FileDiff className="size-4" aria-hidden />} count={changes.data ? `${changes.data.length}` : undefined} />
        {changes.loading && !changes.data ? <div className="px-5"><LoadingState /></div> : !changes.data?.length ? (
          <EmptyState title="No change sets yet" body="A change set is created when a newer release is submitted or two releases are compared." />
        ) : (
          <TableWrap minWidth="min-w-[720px]">
            <thead><tr><Th>Compared</Th><Th>Changes</Th><Th>Retest</Th><Th>Reusable</Th><Th>Notes</Th><Th>Plan</Th><Th>Created</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {changes.data.map((c) => (
                <tr key={c.id}>
                  <Td><Link href={`/changes/${c.id}`} className="font-medium hover:underline">{c.base ?? "none"} → {c.target}</Link></Td>
                  <Td>{c.changes.length}</Td>
                  <Td>{c.retest.length}</Td>
                  <Td>{c.reusable.length}</Td>
                  <Td className="text-xs">
                    {c.partial_collection && <StatusBadge status="stale" label="Partial collection" />}{" "}
                    {c.conservative_fallback && <StatusBadge status="unknown" label="Conservative fallback" />}
                    {!c.partial_collection && !c.conservative_fallback && <span className="text-muted">Mapped changes only</span>}
                  </Td>
                  <Td><Mono>{c.plan_id}</Mono></Td>
                  <Td className="whitespace-nowrap text-muted">{formatTime(c.created_at)}<span className="block text-xs">{c.created_by}</span></Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
    </div>
  );
}

export default function ApplicationReleasesPage() {
  return <WithSuspense label="Loading releases…"><ReleasesView /></WithSuspense>;
}
