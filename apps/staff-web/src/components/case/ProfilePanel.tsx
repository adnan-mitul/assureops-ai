"use client";

import { post, usePoll } from "@assureops/ui/client";
import { Button, Card, CardHeader, EmptyState, inputClass, Notice, StatusBadge } from "@assureops/ui/components";
import { CircleCheck, CircleDashed, PlugZap, ScrollText } from "lucide-react";
import { useState } from "react";
import { useStaffAction } from "@/lib/actions";
import { ActionDone, ActionError } from "@/components/staff-ui";
import type { Duty } from "@/lib/types";

type ProfileRow = {
  revision: number; status: string; source: string; proposed_by: string; reviewed_by: string | null; profile_id: string; version: string;
  scope: string | null; assessed_controls: string[]; unassessed_controls: string[];
  tests: { id: string; control: string; severity: string; name: string; template: string; requires_review?: boolean }[];
};
export type ConnectionSummary = {
  revision: number; adapter_id: string; status: string; config: Record<string, unknown>;
  verification: { checks?: { id: string; status: string; detail: string }[]; gaps?: string[] };
  actors: Record<string, { secret: { fingerprint: string; revoked: boolean } | null }>;
} | null;

/** Application profile and connection as seen by the assigned staff; proposed revisions are reviewed here by the reviewer duty. */
export function ProfilePanel({ caseId, duty, connection }: { caseId: string; duty: Duty; connection: ConnectionSummary }) {
  const profiles = usePoll<ProfileRow[]>(`/v1/staff/cases/${caseId}/profiles`, 15000);
  const action = useStaffAction(profiles.refresh);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const active = profiles.data?.find((p) => p.status === "active");

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card className="p-5">
        <CardHeader title="Connection" icon={<PlugZap className="size-4" aria-hidden />}
          action={connection ? <StatusBadge status={connection.status === "verified" ? "supported" : "unverified"} label={connection.status} /> : undefined} />
        {!connection ? <EmptyState title="Not connected" body="The customer has not connected this application yet." /> : (
          <div className="mt-3 space-y-2 text-sm">
            <p className="text-muted">r{connection.revision} · {connection.adapter_id} · {String(connection.config.base_url ?? "")}</p>
            <ul className="space-y-1">{connection.verification.checks?.map((c) => (
              <li key={c.id} className="flex gap-2">{c.status === "pass" ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />
                : <CircleDashed className={`mt-0.5 size-4 shrink-0 ${c.status === "gap" ? "text-amber-600" : "text-red-600"}`} aria-hidden />}
                <span><span className="font-medium">{c.id.replaceAll("_", " ")}</span> <span className="text-muted">{c.detail}</span></span></li>))}</ul>
            {!!connection.verification.gaps?.length && <Notice tone="warn"><ul className="list-disc pl-5">{connection.verification.gaps.map((g) => <li key={g}>{g}</li>)}</ul></Notice>}
            <p className="text-xs text-muted">Actors: {Object.entries(connection.actors).map(([n, a]) => `${n} (${a.secret?.fingerprint ?? "missing"})`).join(", ")}</p>
          </div>)}
      </Card>
      <Card className="p-5">
        <CardHeader title="Control profile" icon={<ScrollText className="size-4" aria-hidden />} />
        {active ? (
          <div className="mt-3 text-sm">
            <p className="font-semibold">{active.profile_id} {active.version} (r{active.revision})</p>
            <p className="text-xs text-muted">proposed by {active.proposed_by} · activated by {active.reviewed_by} · source {active.source}</p>
            {active.scope && <p className="mt-1 text-muted">{active.scope}</p>}
            <p className="mt-2 text-xs"><span className="font-medium">Assessed:</span> {active.assessed_controls.join(", ")}</p>
            <p className="text-xs"><span className="font-medium">Not assessed (must stay visible in reports):</span> {active.unassessed_controls.join(", ") || "none"}</p>
          </div>) : <EmptyState title="No active profile" body="Assessments cannot start until a reviewed profile is active." />}
        <ActionError error={action.error} />
        <ActionDone message={action.done} />
        {profiles.data?.filter((p) => p.status === "proposed").map((p) => (
          <div key={p.revision} className="mt-4 rounded-lg border border-line p-3 text-sm">
            <p className="font-medium">Proposed r{p.revision}: {p.profile_id} {p.version} <span className="text-xs text-muted">by {p.proposed_by} ({p.source})</span></p>
            <p className="text-xs">Tests: {p.tests.length} · assessed {p.assessed_controls.join(", ")}</p>
            {duty === "reviewer" ? (
              <div className="mt-2 flex flex-wrap gap-2">
                <input aria-label="Review note" className={`${inputClass} max-w-sm`} placeholder="Review note" value={notes[p.revision] ?? ""}
                  onChange={(e) => setNotes({ ...notes, [p.revision]: e.target.value })} />
                <Button variant="primary" disabled={!!action.busy} onClick={() => action.run(`a${p.revision}`, () => post(`/v1/staff/cases/${caseId}/profile-reviews`,
                  { revision: p.revision, decision: "activate", note: notes[p.revision] ?? "" }), `Profile r${p.revision} activated.`)}>Activate</Button>
                <Button variant="danger" disabled={!!action.busy} onClick={() => action.run(`r${p.revision}`, () => post(`/v1/staff/cases/${caseId}/profile-reviews`,
                  { revision: p.revision, decision: "reject", note: notes[p.revision] ?? "" }), `Profile r${p.revision} rejected.`)}>Reject</Button>
              </div>) : <p className="mt-1 text-xs text-muted">The independent reviewer on this case decides proposed revisions.</p>}
          </div>))}
      </Card>
    </div>
  );
}
