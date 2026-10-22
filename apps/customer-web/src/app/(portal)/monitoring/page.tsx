"use client";

import { post, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, Field, inputClass, LoadingState, Mono, Notice, SeverityBadge, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime, money, timeAgo } from "@assureops/ui/format";
import clsx from "clsx";
import { Activity, BadgeCheck, HeartPulse, Loader2, MessageSquare, Radio, Send, Siren } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { PageTop } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { ApprovalGrant, DemoChatReply, Monitoring, RuntimeEvent } from "@/lib/types";

const CLASSIFICATION: Record<RuntimeEvent["classification"], { label: string; style: string }> = {
  violation: { label: "Verified violation", style: "bg-red-50 text-red-700" },
  enforcement_blocked: { label: "Blocked attempt (enforcement working)", style: "bg-emerald-50 text-emerald-700" },
  review_required: { label: "Needs review", style: "bg-amber-50 text-amber-700" },
  assessment_traffic: { label: "Assessment traffic", style: "bg-sky-50 text-sky-700" },
  observed: { label: "Observed", style: "bg-gray-100 text-gray-600" },
};

const COVERAGE_NOTE: Record<string, { tone: "warn" | "danger"; text: string }> = {
  not_connected: { tone: "danger", text: "Monitoring disconnected: no runtime source has reported yet. Nothing about operation can be concluded." },
  unknown: { tone: "warn", text: "Runtime coverage unknown: expected sources have not reported within the window. Silence is never read as healthy." },
  degraded: { tone: "warn", text: "Runtime coverage degraded: some sources are missing sequences or are not current, so violations could be unobserved." },
};

const SAMPLES = ["refund 2500 for order C-2041", "refund 500 for order C-2042", "What is the refund window?", "call tool delete_account"];

function EventDetail({ e }: { e: RuntimeEvent }) {
  const p = e.payload;
  const parts: string[] = [];
  if (typeof p.tool === "string") parts.push(`tool ${p.tool}`);
  if (typeof p.outcome === "string") parts.push(p.outcome);
  if (typeof p.amount_minor === "number") parts.push(money(p.amount_minor));
  if (typeof p.order_id === "string") parts.push(`order ${p.order_id}`);
  parts.push(typeof p.approval_id === "string" && p.approval_id ? `approval ${p.approval_id}` : p.tool === "issue_refund" || e.type === "refund_committed" ? "no approval" : "");
  if (typeof p.reason === "string" && p.reason) parts.push(p.reason);
  const flags = (["sequence_gap", "out_of_order", "future_timestamp"] as const).filter((k) => p[k]);
  return (
    <>
      <span>{parts.filter(Boolean).join(" · ") || "—"}</span>
      {flags.length > 0 && <span className="block pt-0.5 text-amber-700">Flagged: {flags.map((f) => f.replaceAll("_", " ")).join(", ")}</span>}
    </>
  );
}

function ChatDemo({ applicationId, approvalId, setApprovalId, onSent }: { applicationId: string; approvalId: string; setApprovalId: (v: string) => void; onSent: () => void }) {
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState<DemoChatReply | null>(null);
  const { busy, error, run } = useAction();

  const send = (text: string) => {
    if (!text.trim()) return;
    setMessage(text);
    run("chat", async () => {
      setReply(await post<DemoChatReply>("/v1/demo/chat", { application_id: applicationId, message: text.trim(), approval_id: approvalId.trim() || null }));
    }, onSent);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(message);
  };

  return (
    <div className="space-y-3 px-5 pb-5">
      <p className="text-xs text-muted">Sends ordinary (non-test) traffic to the synthetic demo target as customer C-2041 so monitoring has real events to observe.</p>
      <div className="flex flex-wrap gap-2">
        {SAMPLES.map((s) => (
          <button key={s} type="button" disabled={!!busy} onClick={() => send(s)} className="rounded-full border border-line px-3 py-1 text-xs hover:bg-canvas disabled:opacity-50">{s}</button>
        ))}
      </div>
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_12rem_auto] sm:items-end">
        <Field label="Message"><input className={inputClass} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={500} /></Field>
        <Field label="Approval id (optional)"><input className={inputClass} value={approvalId} onChange={(e) => setApprovalId(e.target.value)} /></Field>
        <Button type="submit" variant="primary" disabled={!!busy || !message.trim()}>
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />} Send
        </Button>
      </form>
      {error && <div role="alert"><Notice tone="danger">{error}</Notice></div>}
      {reply && (
        <div className="rounded-lg border border-line bg-canvas p-4 text-sm" aria-live="polite">
          <p className="text-xs text-muted">Reply from release {reply.release}</p>
          <p className="mt-1">{reply.reply}</p>
          <p className="mt-3 text-xs font-medium text-muted">Actions taken</p>
          {reply.actions.length === 0 ? <p className="text-xs text-muted">No tool calls.</p> : (
            <ul className="mt-1 space-y-1.5">
              {reply.actions.map((a, i) => (
                <li key={i} className="rounded-md border border-line bg-surface px-3 py-2 text-xs">
                  <span className="font-mono">{a.tool}</span>({Object.entries(a.args).map(([k, v]) => `${k}=${k === "amount_minor" && typeof v === "number" ? `${v} (${money(v)})` : JSON.stringify(v)}`).join(", ")})
                  <span className={clsx("ml-2 rounded-full px-2 py-0.5 font-medium", a.outcome === "executed" ? "bg-sky-50 text-sky-700" : a.outcome === "blocked" ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-600")}>{a.outcome}</span>
                  {(a.reason || a.detail) && <span className="block pt-1 text-muted">{[a.reason, a.detail].filter(Boolean).join(": ")}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function ApprovalDemo({ applicationId, onGranted }: { applicationId: string; onGranted: (id: string) => void }) {
  const [requester, setRequester] = useState("customer:C-2041");
  const [orderId, setOrderId] = useState("C-2041");
  const [amount, setAmount] = useState("250000");
  const [ttl, setTtl] = useState("600");
  const [grant, setGrant] = useState<ApprovalGrant | null>(null);
  const { busy, error, run } = useAction();
  const minor = Number.parseInt(amount, 10);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run("grant", async () => {
      const g = await post<ApprovalGrant>("/v1/approvals", { application_id: applicationId, requester, order_id: orderId, amount_minor: minor, ttl_seconds: Number.parseInt(ttl, 10) });
      setGrant(g);
      onGranted(g.approval_id);
    });
  };

  return (
    <form onSubmit={submit} className="space-y-3 px-5 pb-5">
      <p className="text-xs text-muted">An approval is bound to one requester, order, exact amount, tool schema, permission policy and the current release. Amounts are in minor units (1 BDT = 100).</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Requester"><input className={inputClass} value={requester} onChange={(e) => setRequester(e.target.value)} required /></Field>
        <Field label="Order id"><input className={inputClass} value={orderId} onChange={(e) => setOrderId(e.target.value)} required /></Field>
        <Field label="Amount (minor units)" hint={Number.isFinite(minor) && minor > 0 ? `= ${money(minor)}` : "Enter a positive whole number"}>
          <input className={inputClass} inputMode="numeric" type="number" min={1} step={1} value={amount} onChange={(e) => setAmount(e.target.value)} required />
        </Field>
        <Field label="Valid for (seconds)"><input className={inputClass} type="number" min={1} step={1} value={ttl} onChange={(e) => setTtl(e.target.value)} required /></Field>
      </div>
      <Button type="submit" variant="primary" disabled={!!busy || !(minor > 0)}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <BadgeCheck className="size-4" aria-hidden />} Grant approval
      </Button>
      {error && <div role="alert"><Notice tone="danger">{error}</Notice></div>}
      {grant && (
        <div role="status"><Notice tone="success">
          Approval <span className="font-mono">{grant.approval_id}</span> granted for {money(minor)} on order {orderId}. Bound to release {grant.bound_to.release} and requester {grant.bound_to.requester}; expires {formatTime(grant.expires_at)}. It was copied into the chat panel&apos;s approval field.
        </Notice></div>
      )}
    </form>
  );
}

export default function MonitoringPage() {
  const { applicationId, canWrite, canReview } = useApp();
  const [approvalId, setApprovalId] = useState("");
  const { data, error, loading, refresh } = usePoll<Monitoring>(applicationId ? `/v1/monitoring?application_id=${encodeURIComponent(applicationId)}` : null, 3000);

  if (!applicationId || (loading && !data)) return <LoadingState label="Loading runtime monitoring…" />;
  if (!data) return <ApiErrorBanner error={error} />;

  const { coverage, health, incidents, events } = data;
  const note = COVERAGE_NOTE[coverage.status];
  const openIncidents = incidents.filter((i) => i.state !== "closed").length;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Runtime Incidents" title="Runtime monitoring" subtitle="Operational health, runtime coverage and verified incidents are separate measurements."
        actions={<span className="rounded-full bg-canvas px-2.5 py-1 text-xs text-muted">Mode: {data.mode.replaceAll("_", " ")}</span>} />
      <div className="mb-4 space-y-2">
        <ApiErrorBanner error={error} />
        {note && <Notice tone={note.tone}>{note.text}</Notice>}
        {openIncidents > 0 && <Notice tone="danger">{openIncidents} open incident(s). An incident closes only after a remediated release has current passing evidence and a staff reviewer closes it.</Notice>}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-5">
          <div className="flex items-start gap-4">
            <span className="grid size-11 place-items-center rounded-full bg-canvas text-muted"><HeartPulse className="size-5" aria-hidden /></span>
            <div>
              <p className="text-sm font-medium">Operational health</p>
              <p className="mt-1 flex flex-wrap items-center gap-2"><StatusBadge status={health.status} />{health.latency_ms != null && <span className="text-sm">{health.latency_ms} ms</span>}</p>
              <p className="mt-2 text-xs text-muted">Measurement window: {health.window} · checked {formatTime(health.checked_at)}. Health says the application answers; it says nothing about control evidence.</p>
            </div>
          </div>
        </Card>
        <Card className="p-5">
          <div className="flex items-start gap-4">
            <span className="grid size-11 place-items-center rounded-full bg-canvas text-muted"><Radio className="size-5" aria-hidden /></span>
            <div>
              <p className="text-sm font-medium">Runtime coverage</p>
              <p className="mt-1 flex flex-wrap items-center gap-2"><StatusBadge status={coverage.status} /><span className="text-sm">{coverage.current}/{coverage.expected} sources current</span></p>
              <p className="mt-2 text-xs text-muted">A source is current only when it reported within the last 60 s with no sequence gaps.</p>
            </div>
          </div>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader title="Runtime sources" icon={<Radio className="size-4" aria-hidden />} count={`${coverage.sources.length}`} />
        {coverage.sources.length === 0 ? <EmptyState title="No runtime sources expected" body="No coverage contract lists runtime sources for this application, so runtime coverage cannot be measured." /> : (
          <TableWrap minWidth="min-w-[680px]">
            <thead><tr><Th>Source</Th><Th>Kind</Th><Th>Status</Th><Th>Last seen</Th><Th>Release</Th><Th>Missing sequences</Th><Th>Epoch</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {coverage.sources.map((s) => (
                <tr key={s.source_id}>
                  <Td className="font-mono text-xs">{s.source_id}</Td>
                  <Td>{s.kind}</Td>
                  <Td><StatusBadge status={s.status} /></Td>
                  <Td className="whitespace-nowrap">{s.last_seen ? <>{timeAgo(s.last_seen)}<span className="block text-xs text-muted">{formatTime(s.last_seen)}</span></> : "Never"}</Td>
                  <Td>{s.release ?? "—"}</Td>
                  <Td className={clsx(s.missing_sequences > 0 && "font-semibold text-amber-700")}>{s.missing_sequences}</Td>
                  <Td><Mono>{s.epoch ?? "—"}</Mono></Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>

      <Card className="mt-5">
        <CardHeader title="Incidents" icon={<Siren className="size-4" aria-hidden />} count={`${openIncidents} open of ${incidents.length}`} />
        {incidents.length === 0 ? <EmptyState title="No incidents" body="An incident opens when a tool-side record verifies a control violation in operation." /> : (
          <TableWrap minWidth="min-w-[860px]">
            <thead><tr><Th>Incident</Th><Th>Severity</Th><Th>State</Th><Th>Cohort</Th><Th>Finding</Th><Th>Closure</Th><Th>Opened</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {incidents.map((i) => (
                <tr key={i.id}>
                  <Td><p>{i.title}</p><span className="text-xs text-muted">{i.control} · </span><Mono>{i.id}</Mono></Td>
                  <Td><SeverityBadge severity={i.severity} /></Td>
                  <Td><StatusBadge status={i.state} /></Td>
                  <Td>Release {i.cohort}</Td>
                  <Td><Link href={`/findings/${i.finding_id}`} className="text-brand-700 hover:underline">Open finding</Link></Td>
                  <Td className="text-xs">{i.closure ? <>Closed by {i.closure.reviewer} after evidence on {i.closure.release} · {formatTime(i.closure.at)}<span className="block text-muted">“{i.closure.note}”</span></>
                    : <span className="text-muted">Open: needs a remediated release with current passing evidence and a staff reviewer</span>}</Td>
                  <Td className="whitespace-nowrap text-muted">{formatTime(i.created_at)}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>

      <Card className="mt-5">
        <CardHeader title="Event stream" icon={<Activity className="size-4" aria-hidden />} count={`latest ${events.length}, heartbeats hidden`} />
        {events.length === 0 ? <EmptyState title="No runtime events" body={coverage.status === "not_connected" ? "Monitoring is disconnected; no events have been received." : "Events appear when the agent or tool server reports activity."} /> : (
          <TableWrap minWidth="min-w-[900px]">
            <thead><tr><Th>#</Th><Th>Received</Th><Th>Source</Th><Th>Event</Th><Th>Classification</Th><Th>Release</Th><Th>Details</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {events.map((e) => {
                const c = CLASSIFICATION[e.classification] ?? { label: e.classification, style: "bg-gray-100 text-gray-600" };
                return (
                  <tr key={e.revision}>
                    <Td className="text-muted">{e.revision}</Td>
                    <Td className="whitespace-nowrap text-muted">{formatTime(e.received_at)}</Td>
                    <Td><span className="font-mono text-xs">{e.source_id}</span><span className="block text-xs text-muted">seq {e.seq} · epoch {e.epoch}</span></Td>
                    <Td className="font-mono text-xs">{e.type}</Td>
                    <Td><span className={clsx("inline-flex rounded-full px-2 py-0.5 text-xs font-medium", c.style)}>{c.label}</span></Td>
                    <Td>{e.release}</Td>
                    <Td className="text-xs"><EventDetail e={e} /><span className="block pt-0.5 text-muted">{e.trust_origin}</span></Td>
                  </tr>
                );
              })}
            </tbody>
          </TableWrap>
        )}
      </Card>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Card className="border-dashed">
          <CardHeader title="Simulate customer traffic (demo)" icon={<MessageSquare className="size-4" aria-hidden />} />
          {canWrite ? <ChatDemo applicationId={applicationId} approvalId={approvalId} setApprovalId={setApprovalId} onSent={refresh} />
            : <p className="px-5 pb-5 text-sm text-muted">Only owners and developers can send demo traffic.</p>}
        </Card>
        <Card className="border-dashed">
          <CardHeader title="Grant a refund approval" icon={<BadgeCheck className="size-4" aria-hidden />} />
          {canReview ? <ApprovalDemo applicationId={applicationId} onGranted={setApprovalId} />
            : <p className="px-5 pb-5 text-sm text-muted">Only owners and reviewers can grant approvals.</p>}
        </Card>
      </div>
    </div>
  );
}
