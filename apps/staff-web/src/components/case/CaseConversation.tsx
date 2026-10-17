"use client";

import { post } from "@assureops/ui/client";
import { Button, Card, CardHeader, EmptyState, Field, inputClass, StatusBadge } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import clsx from "clsx";
import { FileQuestion, MessagesSquare } from "lucide-react";
import { useState } from "react";
import { ActionDone, ActionError, VisibilityBadge } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import type { CaseDetail } from "@/lib/types";

export function EvidenceRequests({ data, onChange }: { data: CaseDetail; onChange: () => void }) {
  const [body, setBody] = useState("");
  const action = useStaffAction(onChange);

  return (
    <Card className="mb-5">
      <CardHeader title="Evidence requests" icon={<FileQuestion className="size-4" aria-hidden />} count={`${data.evidence_requests.length}`} />
      {data.evidence_requests.length === 0 ? <EmptyState title="No evidence requests" body="Ask the customer for missing information; the case moves to awaiting customer." /> : (
        <ul className="divide-y divide-line border-t border-line">
          {data.evidence_requests.map((r) => (
            <li key={r.id} className="px-5 py-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-muted">{r.requested_by} · {formatTime(r.at)}</span>
                <StatusBadge status={r.state} />
              </div>
              <p className="mt-1 whitespace-pre-wrap">{r.body}</p>
              {r.response && <p className="mt-2 rounded-lg bg-canvas px-3 py-2 text-[13px]"><span className="text-xs text-muted">Customer response{r.responded_by ? ` from ${r.responded_by}` : ""}: </span>{r.response}</p>}
            </li>
          ))}
        </ul>
      )}
      <form className="space-y-2 border-t border-line px-5 py-4" onSubmit={async (e) => {
        e.preventDefault();
        const ok = await action.run("request", () => post<{ ok: boolean; state: string }>(`/v1/staff/cases/${data.id}/evidence-requests`, { body: body.trim() }),
          "Request sent to the customer.");
        if (ok) setBody("");
      }}>
        <Field label="New evidence request (visible to the customer)" hint="Requests are always customer-visible. Use an internal note for staff-only context.">
          <textarea required minLength={3} rows={2} value={body} onChange={(e) => setBody(e.target.value)} className={inputClass} />
        </Field>
        <Button type="submit" disabled={action.busy !== null || body.trim().length < 3}>{action.busy ? "Sending…" : "Send request to customer"}</Button>
        <ActionError error={action.error} />
        <ActionDone message={action.done} />
      </form>
    </Card>
  );
}

export function MessageThread({ data, onChange }: { data: CaseDetail; onChange: () => void }) {
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState<"internal" | "customer">("internal");
  const action = useStaffAction(onChange);
  const internalCount = data.messages.filter((m) => m.visibility === "internal").length;

  return (
    <Card className="mb-5">
      <CardHeader title="Case messages" icon={<MessagesSquare className="size-4" aria-hidden />}
        count={`${data.messages.length} · ${internalCount} internal`} />
      {data.messages.length === 0 ? <EmptyState title="No messages yet" body="Internal notes stay with staff; customer-visible messages appear in the customer's case view." /> : (
        <ol className="space-y-3 border-t border-line px-5 py-4">
          {data.messages.map((m) => (
            <li key={m.id} className={clsx("rounded-lg px-4 py-3 text-sm",
              m.visibility === "internal" ? "border-l-4 border-slate-700 bg-slate-100" : "border border-sky-200 bg-surface")}>
              <div className="flex flex-wrap items-center gap-2">
                <VisibilityBadge visibility={m.visibility} />
                <span className="text-xs font-medium">{m.author}</span>
                <span className="text-xs text-muted">({m.author_kind}) · {formatTime(m.at)}</span>
              </div>
              <p className="mt-1.5 whitespace-pre-wrap">{m.body}</p>
            </li>
          ))}
        </ol>
      )}
      <form className="space-y-3 border-t border-line px-5 py-4" onSubmit={async (e) => {
        e.preventDefault();
        const ok = await action.run("send", () => post(`/v1/staff/cases/${data.id}/messages`, { body: body.trim(), visibility }),
          visibility === "internal" ? "Internal note added (staff only)." : "Message sent; the customer can see it.");
        if (ok) { setBody(""); setVisibility("internal"); }
      }}>
        <fieldset>
          <legend className="mb-1.5 text-xs font-medium text-muted">Who can see this message?</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className={clsx("flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm", visibility === "internal" ? "border-slate-700 bg-slate-100" : "border-line")}>
              <input type="radio" name="visibility" className="mt-0.5" checked={visibility === "internal"} onChange={() => setVisibility("internal")} />
              <span><span className="font-medium">Internal note</span><span className="block text-xs text-muted">Staff on this case only. Never shown to the customer.</span></span>
            </label>
            <label className={clsx("flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm", visibility === "customer" ? "border-sky-500 bg-sky-50" : "border-line")}>
              <input type="radio" name="visibility" className="mt-0.5" checked={visibility === "customer"} onChange={() => setVisibility("customer")} />
              <span><span className="font-medium">Customer-visible message</span><span className="block text-xs text-muted">Appears in the customer&apos;s case thread.</span></span>
            </label>
          </div>
        </fieldset>
        <Field label={visibility === "internal" ? "Internal note" : "Message to the customer"}>
          <textarea required maxLength={4000} rows={3} value={body} onChange={(e) => setBody(e.target.value)} className={inputClass} />
        </Field>
        <Button type="submit" variant={visibility === "customer" ? "primary" : "secondary"} disabled={action.busy !== null || !body.trim()}>
          {action.busy ? "Sending…" : visibility === "internal" ? "Add internal note" : "Send to customer"}
        </Button>
        <ActionError error={action.error} />
        <ActionDone message={action.done} />
      </form>
    </Card>
  );
}
