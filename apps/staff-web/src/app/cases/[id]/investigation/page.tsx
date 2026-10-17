"use client";

import { post, usePoll } from "@assureops/ui/client";
import {
  ApiErrorBanner, Button, Card, CardHeader, EmptyState, Field, inputClass, LoadingState, Mono, Notice, SeverityBadge, StatusBadge, TableWrap, Td, Th,
} from "@assureops/ui/components";
import { formatTime, shortHash } from "@assureops/ui/format";
import { Fingerprint, GitBranch, Network, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, Suspense, useState } from "react";
import { ActionDone, ActionError, CaseTabs, KeyValue, RevisionDrift, SectionTitle } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import type { DependencyEdge, Investigation } from "@/lib/types";

function listOrDash(values: unknown[] | undefined) {
  if (!values || values.length === 0) return <span className="text-muted">None declared</span>;
  return <ul className="space-y-0.5">{values.map((v, i) => <li key={i} className="font-mono text-[11px]">{typeof v === "string" ? v : JSON.stringify(v)}</li>)}</ul>;
}

function EdgeReviewForm({ caseId, edge, current, onDone, onClose, onSuccess }: {
  caseId: string; edge: DependencyEdge; current: DependencyEdge | undefined; onDone: () => void; onClose: () => void; onSuccess: (m: string) => void;
}) {
  const [loaded] = useState(edge);
  const [act, setAct] = useState<"accept" | "reject">(edge.status === "accepted" ? "reject" : "accept");
  const [rationale, setRationale] = useState("");
  const action = useStaffAction(onDone);
  const name = `edge-${edge.id}`;

  return (
    <form className="space-y-3 bg-canvas px-5 py-4" onSubmit={async (e) => {
      e.preventDefault();
      const result = await action.run("review", () => post<{ status: string; revision: number }>(`/v1/staff/cases/${caseId}/coverage-reviews`, {
        test_id: loaded.test_id, component_id: loaded.component_id, action: act, rationale: rationale.trim(), expected_revision: loaded.revision,
      }));
      if (result) onSuccess(`Edge ${loaded.test_id} → ${loaded.component_id} is now ${result.status} (revision ${result.revision}).`);
    }}>
      <p className="text-sm">Review edge <Mono>{loaded.test_id}</Mono> → <Mono>{loaded.component_id}</Mono> (currently {loaded.status}, revision {loaded.revision}).</p>
      <RevisionDrift loaded={loaded.revision} current={current?.revision} what="edge" />
      <fieldset>
        <legend className="mb-1 text-xs font-medium text-muted">Decision</legend>
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="radio" name={name} checked={act === "accept"} onChange={() => setAct("accept")} /> Accept edge</label>
          <label className="flex items-center gap-2"><input type="radio" name={name} checked={act === "reject"} onChange={() => setAct("reject")} /> Reject edge</label>
        </div>
      </fieldset>
      {act === "reject" && loaded.status === "accepted" && (
        <Notice tone="warn">Rejecting an accepted edge changes the dependency map: evidence for {loaded.test_id} that was reused on the basis of this edge becomes stale and needs a retest.</Notice>
      )}
      {act === "accept" && loaded.status === "proposed" && (
        <p className="text-xs text-muted">The person who proposed an edge cannot accept it; the API refuses self-acceptance.</p>
      )}
      <Field label="Rationale (required, min. 3 characters)">
        <textarea required minLength={3} rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)} className={inputClass} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant={act === "reject" ? "danger" : "primary"} disabled={action.busy !== null || rationale.trim().length < 3}>
          {action.busy ? "Saving…" : act === "accept" ? "Accept edge" : "Reject edge"}
        </Button>
        <Button onClick={onClose}>Close</Button>
      </div>
      <ActionError error={action.error} />
    </form>
  );
}

function ProposeEdge({ caseId, data, onDone }: { caseId: string; data: Investigation; onDone: () => void }) {
  const components = Object.keys(data.release?.components ?? {}).sort();
  const [testId, setTestId] = useState(data.tests[0]?.id ?? "");
  const [component, setComponent] = useState(components[0] ?? "");
  const [rationale, setRationale] = useState("");
  const action = useStaffAction(onDone);

  return (
    <form className="space-y-3 px-5 py-4" onSubmit={async (e) => {
      e.preventDefault();
      const ok = await action.run("propose", () => post(`/v1/staff/cases/${caseId}/coverage-reviews`,
        { test_id: testId, component_id: component, action: "propose", rationale: rationale.trim() }),
        `Proposed ${testId} → ${component}. Another reviewer must accept it before it affects reuse.`);
      if (ok) setRationale("");
    }}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Test">
          <select value={testId} onChange={(e) => setTestId(e.target.value)} className={inputClass}>
            {data.tests.map((t) => <option key={t.id} value={t.id}>{t.id} — {t.name}</option>)}
          </select>
        </Field>
        <Field label="Release component">
          <select value={component} onChange={(e) => setComponent(e.target.value)} className={inputClass} disabled={components.length === 0}>
            {components.length === 0 && <option value="">No release components collected</option>}
            {components.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Rationale (required, min. 3 characters)" hint="Explain why the test outcome depends on this component.">
        <textarea required minLength={3} rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)} className={inputClass} />
      </Field>
      <Button type="submit" variant="primary" disabled={action.busy !== null || !testId || !component || rationale.trim().length < 3}>
        {action.busy ? "Proposing…" : "Propose edge"}
      </Button>
      <ActionError error={action.error} />
      <ActionDone message={action.done} />
    </form>
  );
}

function InvestigationView() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, refresh } = usePoll<Investigation>(`/v1/staff/cases/${id}/investigation`, 8000);
  const [open, setOpen] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<DependencyEdge | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (loading && !data) return <LoadingState label="Loading investigation…" />;
  if (!data) {
    return (
      <div className="mx-auto max-w-[1400px]">
        <ApiErrorBanner error={error} />
        <Link href="/work-queue" className="text-sm text-brand-700 hover:underline">← Back to work queue</Link>
      </div>
    );
  }

  const { release, coverage_contract: contract, change } = data;
  const hasContract = Object.keys(contract).length > 0;
  const byTest = new Map<string, DependencyEdge[]>();
  for (const e of data.edges) byTest.set(e.test_id, [...(byTest.get(e.test_id) ?? []), e]);
  const testName = (tid: string) => data.tests.find((t) => t.id === tid)?.name ?? tid;
  const orderedTests = [...data.tests.map((t) => t.id), ...[...byTest.keys()].filter((k) => !data.tests.some((t) => t.id === k))];
  const proposed = data.edges.filter((e) => e.status === "proposed").length;

  return (
    <div className="mx-auto max-w-[1400px]">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Link href={`/cases/${id}`} className="text-sm text-brand-700 hover:underline">← {data.case.title}</Link>
        <Button onClick={refresh}><RefreshCw className="size-4" aria-hidden /> Refresh</Button>
      </div>
      <div className="mb-4">
        <h1 className="text-xl font-bold tracking-tight">{data.case.title}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted"><StatusBadge status={data.case.state} /> Investigation · your duty: {data.your_duty}</p>
      </div>
      <CaseTabs caseId={id} active="investigation" />
      {error && <ApiErrorBanner error={error} />}

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="mb-0">
          <CardHeader title="Release identity" icon={<Fingerprint className="size-4" aria-hidden />} />
          {!release ? <EmptyState title="No release collected" body="The customer has not submitted a release." /> : (
            <div className="space-y-3 px-5 pb-5">
              <dl className="grid gap-3 sm:grid-cols-2">
                <KeyValue label="Version">{release.version}</KeyValue>
                <KeyValue label="Manifest hash"><Mono>{release.manifest_hash}</Mono></KeyValue>
                <KeyValue label="Collection status"><StatusBadge status={release.collection_status === "complete" ? "completed" : "incomplete"} label={release.collection_status === "complete" ? "Complete" : "Partial"} /></KeyValue>
                <KeyValue label="MCP protocol version">{release.integration.mcp_protocol_version ?? <span className="text-muted">Not reported</span>}</KeyValue>
                <KeyValue label="Integration">{release.integration.adapter ?? "—"}{release.integration.mode ? ` · ${release.integration.mode}` : ""}</KeyValue>
                <KeyValue label="Collected">{formatTime(release.created_at)}</KeyValue>
              </dl>
              {release.collection_gaps.length > 0 && <Notice tone="warn">Collection gaps: {release.collection_gaps.join("; ")}</Notice>}
              <div>
                <SectionTitle>Components ({Object.keys(release.components).length})</SectionTitle>
                <ul className="grid gap-1 sm:grid-cols-2">
                  {Object.entries(release.components).map(([cid, c]) => (
                    <li key={cid} className="flex items-center justify-between gap-2 rounded-md border border-line px-2 py-1 text-xs">
                      <span className="font-mono">{cid}</span><span className="text-muted">{c.type} · <span className="font-mono">{shortHash(c.fingerprint)}</span></span>
                    </li>
                  ))}
                </ul>
              </div>
              {Object.keys(release.policy_versions).length > 0 && (
                <p className="text-xs text-muted">Policy versions: {Object.entries(release.policy_versions).map(([k, v]) => `${k} ${v}`).join(", ")}</p>
              )}
            </div>
          )}
        </Card>

        <Card className="mb-0">
          <CardHeader title="Coverage contract" icon={<Network className="size-4" aria-hidden />} count={hasContract ? `revision ${contract.revision ?? "—"}` : undefined} />
          {!hasContract ? <EmptyState title="No coverage contract" body="Without a reviewed contract every change is treated conservatively." /> : (
            <div className="space-y-3 px-5 pb-5">
              <dl className="grid gap-3 sm:grid-cols-2">
                <KeyValue label="Adapter">{contract.adapter_id ?? "—"} <span className="text-muted">v{contract.adapter_version ?? "?"}</span></KeyValue>
                <KeyValue label="Reviewed by">{contract.reviewer ?? "—"}</KeyValue>
                <KeyValue label="Reviewed against" className="sm:col-span-2">{contract.reviewed_against ?? "—"}</KeyValue>
              </dl>
              <div>
                <SectionTitle>Mandatory components by control</SectionTitle>
                {Object.keys(contract.mandatory_components ?? {}).length === 0 ? <p className="text-sm text-muted">None declared</p> : (
                  <ul className="space-y-1 text-[13px]">
                    {Object.entries(contract.mandatory_components ?? {}).map(([ctl, comps]) => (
                      <li key={ctl}><span className="font-medium">{ctl}</span>: {comps.length ? <span className="font-mono text-[11px]">{comps.join(", ")}</span> : <span className="text-muted">boundary check only</span>}</li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <SectionTitle>Runtime sources</SectionTitle>
                {(contract.runtime_sources ?? []).length === 0 ? <p className="text-sm text-muted">None declared</p> : (
                  <ul className="space-y-0.5 text-[13px]">{contract.runtime_sources!.map((s) => <li key={s.source_id}><span className="font-mono text-[11px]">{s.source_id}</span> · {s.kind} · {s.environment}</li>)}</ul>
                )}
              </div>
              <dl className="grid gap-3 sm:grid-cols-2">
                <KeyValue label="Unknowns">{listOrDash(contract.unknowns)}</KeyValue>
                <KeyValue label="Exclusions">{listOrDash(contract.exclusions)}</KeyValue>
              </dl>
            </div>
          )}
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader title="Unmapped components" count={`${data.unmapped_components.length}`} />
        <div className="px-5 pb-4">
          {data.unmapped_components.length === 0 ? <p className="text-sm text-muted">Every release component has at least one accepted dependency edge.</p> : (
            <>
              <p className="mb-2 text-sm">These components have no accepted edge. A change to any of them forces a conservative retest because its impact is unknown.</p>
              <ul className="flex flex-wrap gap-1.5">{data.unmapped_components.map((c) => <li key={c} className="rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 font-mono text-[11px] text-amber-800">{c}</li>)}</ul>
            </>
          )}
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="Latest change" icon={<GitBranch className="size-4" aria-hidden />} count={change ? `${change.base ?? "—"} → ${change.target}` : undefined} />
        {!change ? <EmptyState title="No change set" body="A change set is computed when a newer release is submitted." /> : (
          <div className="space-y-4 pb-4">
            {(change.partial_collection || change.conservative_fallback) && (
              <div className="px-5"><Notice tone="warn">{change.partial_collection ? "Partial collection. " : ""}{change.conservative_fallback ? "Conservative fallback: unmapped changes trigger retests." : ""}</Notice></div>
            )}
            {change.changes.length === 0 ? <p className="px-5 text-sm text-muted">No component changed.</p> : (
              <TableWrap minWidth="min-w-[860px]">
                <thead><tr><Th>Component</Th><Th>Change</Th><Th>Before</Th><Th>After</Th><Th>Affected tests</Th><Th>Impact</Th></tr></thead>
                <tbody className="divide-y divide-line">
                  {change.changes.map((c) => (
                    <tr key={c.component}>
                      <Td><Mono>{c.component}</Mono><p className="text-xs text-muted">{c.label}</p></Td>
                      <Td className="capitalize">{c.change}</Td>
                      <Td><Mono>{shortHash(c.before, 12)}</Mono></Td>
                      <Td><Mono>{shortHash(c.after, 12)}</Mono></Td>
                      <Td className="text-xs">{c.affected_tests.length ? c.affected_tests.join(", ") : <span className="text-muted">{c.impact === "unknown" ? "Unmapped" : "None"}</span>}</Td>
                      <Td><SeverityBadge severity={c.impact} /></Td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            )}
            <div className="grid gap-4 px-5 md:grid-cols-2">
              <div>
                <SectionTitle>Retest ({change.retest.length})</SectionTitle>
                {change.retest.length === 0 ? <p className="text-sm text-muted">Nothing to retest.</p> : (
                  <ul className="space-y-1 text-[13px]">{change.retest.map((r) => <li key={r.test_id}><Mono>{r.test_id}</Mono> <span className="text-muted">({r.control})</span> — {r.reasons.join("; ")}</li>)}</ul>
                )}
              </div>
              <div>
                <SectionTitle>Reusable evidence ({change.reusable.length})</SectionTitle>
                {change.reusable.length === 0 ? <p className="text-sm text-muted">No evidence can be reused.</p> : <p className="font-mono text-[11px]">{change.reusable.join(", ")}</p>}
                <p className="mt-2 text-xs text-muted">Edge revision <Mono>{shortHash(change.edge_revision, 12)}</Mono>{change.plan_id ? <> · plan <Mono>{change.plan_id}</Mono></> : null}</p>
              </div>
            </div>
          </div>
        )}
      </Card>

      <Card className="mt-5">
        <CardHeader title="Dependency edges" count={`${data.edges.length} edges · ${proposed} proposed`} />
        <p className="px-5 pb-3 text-xs text-muted">
          Accepted edges decide which evidence is reused after a change. A proposer cannot accept their own edge. Rejecting an accepted edge makes evidence that relied on it stale.
        </p>
        {done && <div className="px-5 pb-3"><ActionDone message={done} /></div>}
        <TableWrap minWidth="min-w-[1000px]">
          <thead><tr><Th>Component</Th><Th>Edge status</Th><Th>Source</Th><Th>Rationale</Th><Th>Reviewer</Th><Th>Revision</Th><Th>Updated</Th><Th className="text-right">Action</Th></tr></thead>
          {orderedTests.map((tid) => {
            const edges = byTest.get(tid) ?? [];
            return (
              <tbody key={tid} className="divide-y divide-line border-t border-line">
                <tr className="bg-canvas"><td colSpan={8} className="px-5 py-2 text-xs font-semibold">{tid} <span className="font-normal text-muted">— {testName(tid)}</span></td></tr>
                {edges.length === 0 ? (
                  <tr><Td className="text-muted" >No edges</Td><td colSpan={7} /></tr>
                ) : edges.map((e) => (
                  <Fragment key={e.id}>
                    <tr>
                      <Td><Mono>{e.component_id}</Mono></Td>
                      <Td><StatusBadge status={e.status} /></Td>
                      <Td className="text-muted">{e.source}</Td>
                      <Td className="max-w-xs text-xs">{e.rationale ?? <span className="text-muted">—</span>}</Td>
                      <Td className="text-xs text-muted">{e.reviewer ?? "—"}</Td>
                      <Td>{e.revision}</Td>
                      <Td className="whitespace-nowrap text-xs text-muted">{formatTime(e.updated_at)}</Td>
                      <Td className="text-right">
                        <Button className="px-2.5 py-1 text-xs" aria-expanded={open === e.id} onClick={() => {
                          if (open === e.id) { setOpen(null); return; }
                          setSnapshot(e); setDone(null); setOpen(e.id);
                        }}>{open === e.id ? "Close" : "Review"}</Button>
                      </Td>
                    </tr>
                    {open === e.id && snapshot && (
                      <tr><td colSpan={8} className="p-0">
                        <EdgeReviewForm key={snapshot.id} caseId={id} edge={snapshot} current={e} onDone={refresh} onClose={() => setOpen(null)}
                          onSuccess={(m) => { setDone(m); setOpen(null); }} />
                      </td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            );
          })}
        </TableWrap>
        <div className="border-t border-line">
          <h3 className="px-5 pt-4 text-sm font-semibold">Propose a new edge</h3>
          <ProposeEdge caseId={id} data={data} onDone={refresh} />
        </div>
      </Card>
    </div>
  );
}

export default function InvestigationPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading investigation…" />}>
      <InvestigationView />
    </Suspense>
  );
}
