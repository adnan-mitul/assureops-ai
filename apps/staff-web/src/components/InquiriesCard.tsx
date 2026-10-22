"use client";

import { post, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, Field, Mono, StatusBadge, inputClass } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { Inbox } from "lucide-react";
import { useState } from "react";
import { ActionDone, ActionError } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";

type Inquiry = { id: string; company: string; contact_email: string; message: string; status: string; workspace_id: string | null; created_at: number };

function slug(company: string): string {
  return company.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 30) || "workspace";
}

/** Public inquiries become verified workspaces; the contact is invited as owner. Converting grants staff no tenant access. */
export function InquiriesCard() {
  const list = usePoll<Inquiry[]>("/v1/staff/inquiries", 20000);
  const action = useStaffAction(() => list.refresh());
  const [drafts, setDrafts] = useState<Record<string, { id: string; name: string }>>({});

  const draft = (i: Inquiry) => drafts[i.id] ?? { id: slug(i.company), name: i.company };
  const open = (list.data ?? []).filter((i) => i.status === "new");

  return (
    <Card>
      <CardHeader title="Inquiries" icon={<Inbox className="size-4" aria-hidden />} count={list.data ? `${open.length} new` : undefined} />
      <ApiErrorBanner error={list.error} />
      <ActionError error={action.error} />
      <ActionDone message={action.done} />
      {list.data && list.data.length === 0 && <div className="p-5"><EmptyState title="No inquiries" body="Inquiries sent from the public contact page appear here." /></div>}
      <ul className="divide-y divide-line">
        {(list.data ?? []).map((i) => (
          <li key={i.id} className="space-y-2 px-5 py-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <strong>{i.company}</strong><Mono>{i.contact_email}</Mono>
              <StatusBadge status={i.status === "new" ? "pending" : "completed"} label={i.status} />
              <span className="text-xs text-muted">{formatTime(i.created_at)}</span>
              {i.workspace_id && <span className="text-xs text-muted">workspace <Mono>{i.workspace_id}</Mono></span>}
            </div>
            <p className="text-muted">{i.message}</p>
            {i.status === "new" && (
              <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => {
                e.preventDefault();
                const d = draft(i);
                action.run(`cv-${i.id}`, () => post(`/v1/staff/inquiries/${i.id}/convert`, { workspace_id: d.id, workspace_name: d.name }),
                  `Workspace ${d.id} created; ${i.contact_email} is invited as owner.`);
              }}>
                <Field label="Workspace id">
                  <input aria-label={`Workspace id for ${i.company}`} required pattern="[a-z0-9-]{3,40}" value={draft(i).id}
                    onChange={(e) => setDrafts({ ...drafts, [i.id]: { ...draft(i), id: e.target.value } })} className={`${inputClass} w-56`} />
                </Field>
                <Field label="Workspace name">
                  <input required minLength={2} value={draft(i).name} onChange={(e) => setDrafts({ ...drafts, [i.id]: { ...draft(i), name: e.target.value } })}
                    className={`${inputClass} w-64`} />
                </Field>
                <Button type="submit" variant="primary" disabled={action.busy !== null}>Create workspace and invite owner</Button>
              </form>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
