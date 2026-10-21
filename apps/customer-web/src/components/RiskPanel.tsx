"use client";

import { pathFor, type RequestBody } from "@assureops/ui/api/contract";
import { post, useAction, usePoll } from "@assureops/ui/client";
import { Button, Card, CardHeader, ErrorBanner, Field, Mono, Notice, StatusBadge, inputClass } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { useApp } from "@/lib/app-context";

type Acceptance = { id: string; control_id: string; severity: string; reason: string; compensating_controls: string; status: string;
  requested_by: string; decided_by: string | null; decision_note: string | null; expires_at: number; applies_to_latest_release: boolean };
type Listing = { policy_max_severity: string | null; max_days: number; items: Acceptance[] };

const STATUS: Record<string, string> = { proposed: "pending", active: "accepted", rejected: "rejected", revoked: "withdrawn", expired: "unknown" };

/** Release-bound risk acceptance for one failed control. The failure itself is never changed. */
export function RiskPanel({ applicationId, control, severity, failing }: { applicationId: string; control: string; severity: string; failing: boolean }) {
  const { me, canWrite } = useApp();
  const list = usePoll<Listing>(`/v1/applications/${applicationId}/risk-acceptances`, 0);
  const action = useAction();
  const [reason, setReason] = useState("");
  const [compensating, setCompensating] = useState("");
  const [days, setDays] = useState(30);
  const items = (list.data?.items ?? []).filter((i) => i.control_id === control);
  const limit = list.data?.policy_max_severity ?? null;
  const canDecide = me?.role === "owner" || me?.role === "reviewer";
  const refresh = () => list.refresh();

  return (
    <Card className="mt-5 p-5">
      <CardHeader title="Risk acceptance" icon={<ShieldAlert className="size-4" aria-hidden />} count={items.length ? `${items.length}` : undefined} />
      <p className="text-sm text-muted">
        Accepting a risk never changes this failure, its evidence or the scores. An approved acceptance applies only to the current release, expires, and needs a
        different person to approve it. {severity === "critical" ? "Critical failures always block and cannot be accepted." :
          limit ? `This application's reviewed profile permits acceptance up to ${limit} severity.` : "This application's profile does not permit risk acceptance, so an approval cannot change the gate."}
      </p>

      {items.length > 0 && (
        <ul className="mt-4 space-y-3">
          {items.map((i) => (
            <li key={i.id} className="rounded-lg border border-line p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={STATUS[i.status] ?? "unknown"} label={i.status} />
                <Mono>{i.id}</Mono>
                <span className="text-xs text-muted">requested by {i.requested_by} · expires {formatTime(i.expires_at)}</span>
                {!i.applies_to_latest_release && <StatusBadge status="superseded" label="older release" />}
              </div>
              <p className="mt-2">{i.reason}</p>
              <p className="mt-1 text-xs text-muted">Compensating controls: {i.compensating_controls}</p>
              {i.decided_by && <p className="mt-1 text-xs text-muted">Decided by {i.decided_by}: {i.decision_note}</p>}
              <div className="mt-2 flex flex-wrap gap-2">
                {i.status === "proposed" && canDecide && i.requested_by !== me?.user && (
                  <>
                    <Button variant="primary" className="px-2 py-1 text-xs" disabled={action.busy !== null}
                      onClick={() => action.run(`ok-${i.id}`, () => post(`/v1/risk-acceptances/${i.id}/decision`, { approve: true, note: "Approved after reviewing the compensating controls" }), refresh)}>
                      Approve
                    </Button>
                    <Button className="px-2 py-1 text-xs" disabled={action.busy !== null}
                      onClick={() => action.run(`no-${i.id}`, () => post(`/v1/risk-acceptances/${i.id}/decision`, { approve: false, note: "Rejected" }), refresh)}>
                      Reject
                    </Button>
                  </>
                )}
                {(i.status === "proposed" || i.status === "active") && me?.role === "owner" && (
                  <Button variant="danger" className="px-2 py-1 text-xs" disabled={action.busy !== null}
                    onClick={() => action.run(`rv-${i.id}`, () => post(`/v1/risk-acceptances/${i.id}/revoke`), refresh)}>
                    Revoke
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {failing && canWrite && severity !== "critical" && (
        <form className="mt-4 grid gap-3" onSubmit={(e) => {
          e.preventDefault();
          const body: RequestBody<"/v1/applications/{application_id}/risk-acceptances", "post"> =
            { control_id: control, reason, compensating_controls: compensating, expires_in_days: days };
          action.run("propose", () => post(pathFor("/v1/applications/{application_id}/risk-acceptances", { application_id: applicationId }), body),
            () => { setReason(""); setCompensating(""); refresh(); });
        }}>
          <Field label="Why ship with this failure?" hint="At least 20 characters">
            <textarea required minLength={20} value={reason} onChange={(e) => setReason(e.target.value)} className={`${inputClass} min-h-20`} />
          </Field>
          <Field label="Compensating controls">
            <textarea required minLength={10} value={compensating} onChange={(e) => setCompensating(e.target.value)} className={`${inputClass} min-h-16`} />
          </Field>
          <Field label={`Expires after (days, at most ${list.data?.max_days ?? 90})`}>
            <input type="number" min={1} max={list.data?.max_days ?? 90} value={days} onChange={(e) => setDays(Number(e.target.value))} className={`${inputClass} w-32`} />
          </Field>
          <div><Button type="submit" variant="primary" disabled={action.busy !== null}>{action.busy === "propose" ? "Requesting…" : "Request risk acceptance"}</Button></div>
        </form>
      )}
      {action.error && <div className="mt-3"><ErrorBanner message={action.error} /></div>}
      {!failing && items.length === 0 && <div className="mt-3"><Notice tone="info">Only an open failed finding can be accepted as a risk.</Notice></div>}
    </Card>
  );
}
