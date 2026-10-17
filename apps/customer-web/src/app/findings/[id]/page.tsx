"use client";

import { ApiError, post, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, Field, inputClass, LoadingState, Mono, Notice, SeverityBadge, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { EvidenceDrawer } from "@assureops/ui/evidence-drawer";
import { formatTime, shortHash } from "@assureops/ui/format";
import { FileCheck2, Loader2, MessagesSquare, Send } from "lucide-react";
import Link from "next/link";
import { useCallback, useState, type FormEvent } from "react";
import { Fact, PageTop, useRouteId, WithSuspense } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { FindingDetail } from "@/lib/types";

const DECISIONS = {
  dispute: { label: "Dispute", hint: "You believe the finding is wrong. It moves to under review; the failing evidence is kept until a staff reviewer decides." },
  remediation_submitted: { label: "Remediation submitted", hint: "You changed the application. The finding stays open until a retest on a new release passes." },
} as const;

function ReviewForm({ finding, onDone }: { finding: FindingDetail; onDone: () => void }) {
  const [decision, setDecision] = useState<keyof typeof DECISIONS>("remediation_submitted");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "danger" | "success" | "warn"; text: string } | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await post(`/v1/findings/${encodeURIComponent(finding.id)}/reviews`, { decision, note: note.trim(), expected_revision: finding.revision });
      setNote("");
      setMessage({ tone: "success", text: `${DECISIONS[decision].label} recorded.` });
    } catch (err) {
      const conflict = err instanceof ApiError && err.status === 409;
      setMessage({ tone: conflict ? "warn" : "danger", text: conflict ? `${err.message}. The finding was reloaded.` : err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
      onDone();
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3 px-5 pb-5">
      <fieldset>
        <legend className="mb-1 text-xs font-medium text-muted">Your response</legend>
        <div className="flex flex-wrap gap-3">
          {(Object.keys(DECISIONS) as (keyof typeof DECISIONS)[]).map((d) => (
            <label key={d} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm has-[:checked]:border-brand-600 has-[:checked]:bg-brand-50">
              <input type="radio" name="decision" value={d} checked={decision === d} onChange={() => setDecision(d)} />
              {DECISIONS[d].label}
            </label>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">{DECISIONS[decision].hint}</p>
      </fieldset>
      <Field label="Note (required)">
        <textarea className={inputClass} rows={3} value={note} onChange={(e) => setNote(e.target.value)} minLength={3} required />
      </Field>
      {message && <div role={message.tone === "success" ? "status" : "alert"}><Notice tone={message.tone}>{message.text}</Notice></div>}
      <Button type="submit" variant="primary" disabled={busy || note.trim().length < 3}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />} Submit response
      </Button>
      <p className="text-xs text-muted">Sent with revision {finding.revision}. If the finding changed since it was loaded, the response is refused and the page reloads.</p>
    </form>
  );
}

function FindingView() {
  const id = useRouteId();
  const { me, canWrite } = useApp();
  const [drawer, setDrawer] = useState<string | null>(null);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const { data: f, error, loading, refresh } = usePoll<FindingDetail>(`/v1/findings/${encodeURIComponent(id)}`, 10000);

  if (loading && !f) return <LoadingState label="Loading finding…" />;
  if (!f) return <ApiErrorBanner error={error} />;

  const canRespond = canWrite || me?.role === "reviewer";
  const runtimeRefs = f.evidence_refs.filter((r) => r.event_revision != null);
  const rationale = f.source === "runtime"
    ? `Critical: a verified runtime violation of ${f.control} ${f.control_name}, corroborated by the tool-side record of the action (not an agent claim).`
    : `${f.severity[0].toUpperCase()}${f.severity.slice(1)}: the fixed severity the versioned assessment profile assigns to test ${f.test_id}. It is not adjusted per finding.`;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow={`Findings · ${f.control} ${f.control_name}`} title={f.title} actions={<><SeverityBadge severity={f.severity} /><StatusBadge status={f.state} /></>} />
      <div className="mb-4 space-y-2">
        <ApiErrorBanner error={error} />
        {f.state === "reopened" && <Notice tone="danger">Reopened: a new failure was recorded after this finding had been resolved.</Notice>}
        {f.state === "under_review" && <Notice tone="warn">Under review: the dispute is with a staff reviewer. The failing evidence still counts until they decide.</Notice>}
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card className="p-5">
          <h2 className="text-[15px] font-semibold">Description</h2>
          <p className="mt-2 text-sm">{f.description}</p>
          <dl className="mt-4 grid gap-4 sm:grid-cols-3">
            <Fact label="Source">{f.source === "runtime" ? "Verified runtime violation" : <>Assessment test <span className="font-mono text-xs">{f.test_id}</span></>}</Fact>
            <Fact label="First seen on">{f.first_release ?? "—"}</Fact>
            <Fact label="Last seen on">{f.last_release ?? "—"}</Fact>
            <Fact label="Created">{formatTime(f.created_at)}</Fact>
            <Fact label="Updated">{formatTime(f.updated_at)}</Fact>
            <Fact label="Revision">{f.revision}</Fact>
          </dl>
          <h3 className="mt-5 text-xs font-semibold tracking-wide text-muted uppercase">Severity rationale</h3>
          <p className="mt-1 text-sm">{rationale}</p>
        </Card>

        <Card className="p-5">
          <h2 className="text-[15px] font-semibold">Resolution</h2>
          <p className="mt-1 text-xs text-muted">A finding resolves only through passing retest evidence on a release, or an audited staff reviewer determination. Customer responses never resolve it on their own.</p>
          {f.resolution ? (
            <div className="mt-3 space-y-1 text-sm">
              <StatusBadge status="resolved" />
              {f.resolution.by === "retest" ? (
                <p>Resolved by a passing retest on {f.resolution.release} · {formatTime(f.resolution.at)}. <button type="button" className="text-brand-700 underline" onClick={() => f.resolution?.by === "retest" && setDrawer(f.resolution.run_id)}>Open evidence</button></p>
              ) : (
                <p>Resolved by reviewer {f.resolution.reviewer} on release {f.resolution.release} · {formatTime(f.resolution.at)}: “{f.resolution.note}”</p>
              )}
            </div>
          ) : <p className="mt-3 text-sm text-muted">Not resolved.</p>}
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader title="Evidence" icon={<FileCheck2 className="size-4" aria-hidden />} count={`${f.evidence.length + runtimeRefs.length}`} />
        {f.evidence.length === 0 && runtimeRefs.length === 0 ? <EmptyState title="No evidence attached" body="Evidence is attached when a test run or runtime event is recorded for this finding." /> : (
          <>
            {f.evidence.length > 0 && (
              <TableWrap minWidth="min-w-[640px]">
                <thead><tr><Th>Test run</Th><Th>Release</Th><Th>Outcome</Th><Th>Availability</Th><Th>Recorded</Th><Th /></tr></thead>
                <tbody className="divide-y divide-line">
                  {f.evidence.map((e) => (
                    <tr key={e.id}>
                      <Td><p>{e.test_name}</p><Mono>{e.id}</Mono></Td>
                      <Td>{e.release}</Td>
                      <Td><StatusBadge status={e.outcome} /><span className="block pt-1 text-xs text-muted">{e.passed_trials}/{e.trials} trials</span></Td>
                      <Td>{e.available ? <Mono>sha256 {shortHash(e.evidence_hash, 12)}</Mono> : <StatusBadge status="unavailable" />}</Td>
                      <Td className="whitespace-nowrap text-muted">{formatTime(e.created_at)}</Td>
                      <Td><button type="button" className="text-xs font-medium text-brand-700 hover:underline" onClick={() => setDrawer(e.id)}>Open evidence</button></Td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            )}
            {runtimeRefs.length > 0 && (
              <div className="border-t border-line px-5 py-3 text-sm">
                <p className="text-xs font-medium text-muted">Runtime events</p>
                <ul className="mt-1 space-y-1">
                  {runtimeRefs.map((r) => <li key={r.event_revision}>Event revision {r.event_revision} on release {r.release} · <Link href="/monitoring" className="text-brand-700 underline">view in Runtime Incidents</Link></li>)}
                </ul>
              </div>
            )}
          </>
        )}
      </Card>

      <Card className="mt-5">
        <CardHeader title="Review thread" icon={<MessagesSquare className="size-4" aria-hidden />} count={`${f.reviews.length}`} />
        {f.reviews.length === 0 ? <EmptyState title="No responses yet" body="Disputes, remediation notes and reviewer decisions appear here in order." /> : (
          <ol className="space-y-3 px-5 pb-5">
            {f.reviews.map((r, i) => (
              <li key={i} className="rounded-lg border border-line p-3 text-sm">
                <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span className="font-medium text-ink">{r.reviewer}</span>
                  <span className="rounded-full bg-canvas px-2 py-0.5">{r.reviewer_kind === "customer" ? "Your team" : r.reviewer_kind}</span>
                  <span className="rounded-full bg-sky-50 px-2 py-0.5 text-sky-700">{r.decision.replaceAll("_", " ")}</span>
                  {formatTime(r.at)}
                </p>
                <p className="mt-1.5">{r.note}</p>
              </li>
            ))}
          </ol>
        )}
        <div className="border-t border-line pt-4">
          {f.state === "resolved" ? <p className="px-5 pb-5 text-sm text-muted">This finding is resolved. It reopens only if new evidence shows the failure again.</p>
            : canRespond ? <ReviewForm finding={f} onDone={refresh} />
            : <p className="px-5 pb-5 text-sm text-muted">Your role can view this finding but cannot respond to it.</p>}
        </div>
      </Card>
      {drawer && <EvidenceDrawer runId={drawer} onClose={closeDrawer} />}
    </div>
  );
}

export default function FindingPage() {
  return <WithSuspense label="Loading finding…"><FindingView /></WithSuspense>;
}
