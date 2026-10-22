"use client";

import { del, post, usePoll } from "@assureops/ui/client";
import {
  ApiErrorBanner, Button, Card, CardHeader, EmptyState, Field, inputClass, LoadingState, Mono, Notice, PageHeader, StatusBadge, TableWrap, Td, Th,
} from "@assureops/ui/components";
import { RefreshCw, UserPlus, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Fragment, Suspense, useState } from "react";
import { ActionDone, ActionError, Assignees, DutyBadge, hoursLabel } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import { useStaff } from "@/lib/staff-context";
import type { Duty, Governance, QueueItem } from "@/lib/types";

function ReassignInline({ caseId, duty, from, staff, run, busy }: {
  caseId: string; duty: Duty; from: string; staff: string[];
  run: (key: string, fn: () => Promise<unknown>, success?: string) => Promise<unknown>; busy: string | null;
}) {
  const [to, setTo] = useState("");
  const options = staff.filter((s) => s !== from);
  return (
    <span className="inline-flex items-center gap-1">
      <label className="sr-only" htmlFor={`re-${caseId}-${from}`}>Reassign the {duty} duty of {from} to</label>
      <select id={`re-${caseId}-${from}`} value={to} onChange={(e) => setTo(e.target.value)} className={`${inputClass} w-52 py-1 text-xs`}>
        <option value="">Reassign to…</option>
        {options.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <Button className="px-2 py-1 text-xs" disabled={!to || busy !== null}
        onClick={() => run(`re-${from}`, () => post(`/v1/staff/cases/${caseId}/reassign`, { duty, from_user: from, to_user: to }), `Moved the ${duty} duty from ${from} to ${to}.`)}>
        {busy === `re-${from}` ? "Moving…" : "Move"}
      </Button>
    </span>
  );
}

function AssignForm({ item, staff, onDone }: { item: QueueItem; staff: string[]; onDone: () => void }) {
  const [user, setUser] = useState(staff[0] ?? "");
  const [duty, setDuty] = useState<Duty>("analyst");
  const action = useStaffAction(onDone);
  const listId = `staff-${item.case_id}`;

  return (
    <div className="space-y-3 bg-canvas px-5 py-4">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-muted">Current assignments</p>
          {item.assignees.length === 0 ? <p className="mt-1 text-sm text-muted">Nobody is assigned.</p> : (
            <ul className="mt-1 space-y-1">
              {item.assignees.map((a) => (
                <li key={`${a.user}-${a.duty}`} className="flex flex-wrap items-center gap-2 text-sm">
                  <span>{a.user ?? "unknown user"}</span>
                  <DutyBadge duty={a.duty} />
                  {a.user && (
                    <Button variant="danger" className="px-2 py-1 text-xs" disabled={action.busy !== null}
                      onClick={() => action.run(`revoke-${a.user}`, () => del(`/v1/staff/cases/${item.case_id}/assignments/${encodeURIComponent(a.user!)}`), `Revoked ${a.user}.`)}>
                      <X className="size-3" aria-hidden /> {action.busy === `revoke-${a.user}` ? "Revoking…" : "Revoke"}
                    </Button>
                  )}
                  {a.user && <ReassignInline caseId={item.case_id} duty={a.duty} from={a.user} staff={staff} run={action.run} busy={action.busy} />}
                </li>
              ))}
            </ul>
          )}
        </div>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => {
          e.preventDefault();
          action.run("assign", () => post(`/v1/staff/cases/${item.case_id}/assignments`, { staff_user: user.trim(), duty }), `Assigned ${user.trim()} as ${duty}.`);
        }}>
          <Field label="Staff user">
            <input list={listId} required value={user} onChange={(e) => setUser(e.target.value)} className={`${inputClass} w-64`} />
            <datalist id={listId}>{staff.map((s) => <option key={s} value={s} />)}</datalist>
          </Field>
          <Field label="Duty">
            <select value={duty} onChange={(e) => setDuty(e.target.value as Duty)} className={`${inputClass} w-48`}>
              <option value="analyst">Analyst</option>
              <option value="reviewer">Independent reviewer</option>
            </select>
          </Field>
          <Button type="submit" variant="primary" disabled={action.busy !== null || !user.trim()}>
            <UserPlus className="size-4" aria-hidden /> {action.busy === "assign" ? "Assigning…" : "Assign"}
          </Button>
        </form>
      </div>
      <p className="text-xs text-muted">The analyst and the independent reviewer must be different people; the API refuses a conflicting assignment.</p>
      <ActionError error={action.error} />
      <ActionDone message={action.done} />
    </div>
  );
}

function WorkQueue() {
  const params = useSearchParams();
  const router = useRouter();
  const q = (params.get("q") ?? "").trim().toLowerCase();
  const { hasRole } = useStaff();
  const { data, error, loading, refresh } = usePoll<QueueItem[]>("/v1/staff/work-queue", 10000);
  const isManager = hasRole("case_manager");
  const { data: gov } = usePoll<Governance>(isManager ? "/v1/staff/governance" : null, 0);
  const [managing, setManaging] = useState<string | null>(null);
  const claim = useStaffAction(refresh);

  // Reassignment targets come from the staff directory: whoever currently holds an analyst or senior reviewer role.
  const staff = Array.from(new Set(gov?.staff_permissions
    .filter((s) => s.roles.includes("analyst") || s.roles.includes("senior_reviewer")).map((s) => s.user) ?? []));

  const rows = (data ?? []).filter((r) => !q || [r.title, r.workspace, r.application, r.state, r.case_id].some((v) => v.toLowerCase().includes(q)));

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Work queue" subtitle="Cases assigned to you, plus newly submitted cases an analyst may claim. Case managers see queue metadata only."
        actions={<Button onClick={refresh}><RefreshCw className="size-4" aria-hidden /> Refresh</Button>} />
      <div className="mb-4 space-y-2">
        <ApiErrorBanner error={error} />
        <ActionError error={claim.error} />
        <ActionDone message={claim.done} />
        {q && <Notice>Filtered by “{params.get("q")}” · {rows.length} of {data?.length ?? 0} cases. <button className="underline" onClick={() => router.push("/work-queue")}>Clear filter</button></Notice>}
      </div>
      <Card>
        <CardHeader title="Cases" count={data ? `${rows.length}` : undefined} />
        {loading && !data ? <div className="px-5"><LoadingState label="Loading work queue…" /></div> : rows.length === 0 ? (
          <EmptyState title={q ? "No matching cases" : "Nothing in your queue"} body={q ? "Try a different search." : "Cases appear here when a customer submits one or a case manager assigns you."} />
        ) : (
          <TableWrap minWidth="min-w-[1100px]">
            <thead>
              <tr><Th>Case</Th><Th>Workspace · application</Th><Th>State</Th><Th>Priority</Th><Th>Blockers</Th><Th>Queue age</Th><Th>Your duty</Th><Th>Assignees</Th><Th className="text-right">Actions</Th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((r) => {
                const hasAnalyst = r.assignees.some((a) => a.duty === "analyst");
                const claimable = hasRole("analyst") && (r.state === "submitted" || r.state === "triage") && !hasAnalyst;
                return (
                  <Fragment key={r.case_id}>
                    <tr>
                      <Td><p className="font-medium">{r.title}</p><Mono>{r.case_id}</Mono></Td>
                      <Td><p>{r.workspace}</p><p className="text-xs text-muted">{r.application}</p></Td>
                      <Td><StatusBadge status={r.state} /></Td>
                      <Td className="capitalize">{r.priority}</Td>
                      <Td>{r.blockers > 0 ? <span className="font-semibold text-red-700">{r.blockers} blocking</span> : <span className="text-muted">None</span>}</Td>
                      <Td className="whitespace-nowrap text-muted" >{hoursLabel(r.queue_age_hours)} <span className="sr-only">since last update</span></Td>
                      <Td><DutyBadge duty={r.your_duty} /></Td>
                      <Td><Assignees assignees={r.assignees} /></Td>
                      <Td className="text-right">
                        <div className="flex flex-wrap justify-end gap-2">
                          {r.your_duty && <Link href={`/cases/${r.case_id}`} className="rounded-lg bg-brand-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-800">Open</Link>}
                          {claimable && (
                            <Button className="px-3 py-1.5 text-xs" disabled={claim.busy !== null}
                              onClick={() => claim.run(r.case_id, () => post(`/v1/staff/cases/${r.case_id}/claim`), `Claimed ${r.title}; you are now its analyst.`)}>
                              {claim.busy === r.case_id ? "Claiming…" : "Claim"}
                            </Button>
                          )}
                          {isManager && (
                            <Button className="px-3 py-1.5 text-xs" onClick={() => setManaging(managing === r.case_id ? null : r.case_id)}>
                              {managing === r.case_id ? "Close" : "Assign"}
                            </Button>
                          )}
                          {!r.your_duty && !claimable && !isManager && <span className="text-xs text-muted">Metadata only</span>}
                        </div>
                      </Td>
                    </tr>
                    {isManager && managing === r.case_id && (
                      <tr><td colSpan={9} className="p-0"><AssignForm item={r} staff={staff} onDone={refresh} /></td></tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </TableWrap>
        )}
      </Card>
      <p className="mt-3 text-xs text-muted">Queue age is the time since the case was last updated. Opening a case requires an active assignment; the API refuses others with “not assigned”.</p>
    </div>
  );
}

export default function WorkQueuePage() {
  return (
    <Suspense fallback={<LoadingState label="Loading work queue…" />}>
      <WorkQueue />
    </Suspense>
  );
}
