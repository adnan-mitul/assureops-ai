"use client";

import { post, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, Field, inputClass, LoadingState, Mono, Notice, StatusBadge } from "@assureops/ui/components";
import { formatTime, shortHash } from "@assureops/ui/format";
import clsx from "clsx";
import { Check, FileQuestion, FileText, Loader2, MessagesSquare, Send } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Fact, PageTop, useRouteId, WithSuspense } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { AssessmentCase, CaseState } from "@/lib/types";

const STAGES: { states: CaseState[]; label: string }[] = [
  { states: ["draft"], label: "Draft" },
  { states: ["submitted"], label: "Submitted" },
  { states: ["triage"], label: "Triage" },
  { states: ["assessment"], label: "Assessment" },
  { states: ["awaiting_customer", "awaiting_review"], label: "Awaiting customer / review" },
  { states: ["published"], label: "Published" },
  { states: ["monitoring"], label: "Monitoring" },
  { states: ["reassessment"], label: "Reassessment" },
];

const STATE_HINT: Partial<Record<CaseState, string>> = {
  submitted: "The AssureOps team has received the case and will triage it.",
  triage: "The team is confirming scope and the authorized boundary.",
  assessment: "Assessment is in progress.",
  awaiting_customer: "Waiting for your team: answer the open evidence requests below.",
  awaiting_review: "Results are with an AssureOps reviewer before a report can be published.",
  published: "A report was published. Monitoring continues for this application.",
  monitoring: "The published release is being monitored in operation.",
  reassessment: "A newer release was submitted, so the case is being reassessed.",
};

function Timeline({ state }: { state: CaseState }) {
  const at = STAGES.findIndex((s) => s.states.includes(state));
  return (
    <ol className="flex flex-wrap gap-2" aria-label="Case progress">
      {STAGES.map((s, i) => {
        const current = i === at;
        return (
          <li key={s.label} aria-current={current ? "step" : undefined}
            className={clsx("flex items-center gap-1.5 rounded-full px-3 py-1 text-xs", current ? "bg-brand-700 font-semibold text-white" : i < at ? "bg-brand-50 text-brand-700" : "bg-canvas text-muted")}>
            {i < at && <Check className="size-3" aria-hidden />}
            {s.label}{current && s.states.length > 1 ? `: ${state === "awaiting_customer" ? "customer" : "review"}` : ""}
            <span className="sr-only">{current ? " (current)" : i < at ? " (reached)" : " (not reached)"}</span>
          </li>
        );
      })}
    </ol>
  );
}

function RespondForm({ caseId, requestId, onDone }: { caseId: string; requestId: string; onDone: () => void }) {
  const [text, setText] = useState("");
  const { busy, error, run } = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run("respond", async () => {
      await post(`/v1/customer/cases/${encodeURIComponent(caseId)}/responses`, { request_id: requestId, response: text.trim() });
      setText("");
    }, onDone);
  };
  return (
    <form onSubmit={submit} className="mt-3 space-y-2">
      <Field label="Your response"><textarea className={inputClass} rows={3} value={text} onChange={(e) => setText(e.target.value)} minLength={3} required /></Field>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <Button type="submit" variant="primary" disabled={!!busy || text.trim().length < 3}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />} Send response
      </Button>
    </form>
  );
}

function MessageForm({ caseId, onDone }: { caseId: string; onDone: () => void }) {
  const [body, setBody] = useState("");
  const { busy, error, run } = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run("message", async () => {
      await post(`/v1/customer/cases/${encodeURIComponent(caseId)}/messages`, { body: body.trim() });
      setBody("");
    }, onDone);
  };
  return (
    <form onSubmit={submit} className="space-y-2 border-t border-line px-5 py-4">
      <Field label="New message"><textarea className={inputClass} rows={3} value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000} required /></Field>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <Button type="submit" disabled={!!busy || !body.trim()}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />} Post message
      </Button>
    </form>
  );
}

function CaseView() {
  const id = useRouteId();
  const { me, canWrite, applications } = useApp();
  const { data: c, error, loading, refresh } = usePoll<AssessmentCase>(`/v1/customer/cases/${encodeURIComponent(id)}`, 8000);

  if (loading && !c) return <LoadingState label="Loading case…" />;
  if (!c) return <ApiErrorBanner error={error} />;

  const canRespond = canWrite || me?.role === "reviewer";
  const open = c.evidence_requests.filter((r) => r.state === "open");
  const appName = applications.find((a) => a.id === c.application_id)?.name ?? c.application_id;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Assessment Cases" title={c.title} subtitle={appName} actions={<StatusBadge status={c.state} />} />
      <div className="mb-4 space-y-2">
        <ApiErrorBanner error={error} />
        {open.length > 0 && <Notice tone="warn">{open.length} evidence request(s) need your response.</Notice>}
      </div>

      <Card className="p-5">
        <Timeline state={c.state} />
        {STATE_HINT[c.state] && <p className="mt-3 text-sm text-muted">{STATE_HINT[c.state]}</p>}
        <dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <Fact label="Case id"><Mono>{c.id}</Mono></Fact>
          <Fact label="Priority"><span className="capitalize">{c.priority}</span></Fact>
          <Fact label="Opened by">{c.created_by}</Fact>
          <Fact label="Opened">{formatTime(c.created_at)}</Fact>
          <Fact label="Updated">{formatTime(c.updated_at)}</Fact>
        </dl>
        <p className="mt-4 text-sm"><span className="text-xs text-muted">Scope note: </span>{c.scope_note}</p>
      </Card>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Evidence requests" icon={<FileQuestion className="size-4" aria-hidden />} count={`${open.length} open of ${c.evidence_requests.length}`} />
          {c.evidence_requests.length === 0 ? <EmptyState title="No evidence requests" body="The assessment team asks here when it needs information from your team." /> : (
            <ol className="space-y-3 px-5 pb-5">
              {c.evidence_requests.map((r) => (
                <li key={r.id} className="rounded-lg border border-line p-4 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs text-muted">{r.requested_by} · {formatTime(r.at)}</p>
                    <StatusBadge status={r.state} />
                  </div>
                  <p className="mt-1.5">{r.body}</p>
                  {r.response && <div className="mt-3 rounded-md bg-canvas p-3"><p className="text-xs text-muted">Answered by {r.responded_by}</p><p className="mt-1">{r.response}</p></div>}
                  {r.state === "open" && (canRespond ? <RespondForm caseId={c.id} requestId={r.id} onDone={refresh} />
                    : <p className="mt-3 text-xs text-muted">Your role cannot answer evidence requests.</p>)}
                </li>
              ))}
            </ol>
          )}
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Messages" icon={<MessagesSquare className="size-4" aria-hidden />} count={`${c.messages.length}`} />
            {c.messages.length === 0 ? <EmptyState title="No messages yet" body="Messages here are visible to your team and the assessment team." /> : (
              <ol className="max-h-[28rem] space-y-3 overflow-y-auto px-5 pb-4">
                {c.messages.map((m) => (
                  <li key={m.id} className={clsx("rounded-lg p-3 text-sm", m.author_kind === "customer" ? "bg-brand-50" : "bg-canvas")}>
                    <p className="text-xs text-muted"><span className="font-medium text-ink">{m.author}</span> · {m.author_kind === "customer" ? "your team" : "AssureOps"} · {formatTime(m.at)}</p>
                    <p className="mt-1 whitespace-pre-wrap">{m.body}</p>
                  </li>
                ))}
              </ol>
            )}
            {canRespond ? <MessageForm caseId={c.id} onDone={refresh} /> : <p className="border-t border-line px-5 py-4 text-xs text-muted">Your role can read messages but cannot post.</p>}
          </Card>

          <Card>
            <CardHeader title="Published reports" icon={<FileText className="size-4" aria-hidden />} count={`${c.reports.length}`} />
            {c.reports.length === 0 ? <EmptyState title="No published reports" body="Reports appear here once the assessment team publishes one." /> : (
              <ul className="divide-y divide-line border-t border-line">
                {c.reports.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-sm">
                    <div>
                      <Link href={`/reports/${r.id}`} className="font-medium hover:underline">Report for {r.release}</Link>
                      <p className="text-xs text-muted">{formatTime(r.at)} · <span className="font-mono">{shortHash(r.sha256, 12)}</span></p>
                    </div>
                    <StatusBadge status={r.state} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

export default function CasePage() {
  return <WithSuspense label="Loading case…"><CaseView /></WithSuspense>;
}
