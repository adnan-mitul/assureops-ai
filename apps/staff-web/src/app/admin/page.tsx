"use client";

import { del, put, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, LoadingState, Mono, Notice, PageHeader, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { Gauge, ShieldPlus, UsersRound } from "lucide-react";
import { InquiriesCard } from "@/components/InquiriesCard";
import { ActionDone, ActionError } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import { ROLE_LABEL, useStaff } from "@/lib/staff-context";

type StaffRow = { user: string; name: string; active: boolean; roles: string[];
  history: { role: string; active: boolean; granted_by: string | null; granted_at: number | null; revoked_by: string | null; revoked_at: number | null }[] };
type StaffList = { staff: StaffRow[]; assignable_roles: string[] };
type Workload = { staff: { user: string; name: string; roles: string[]; analyst_cases: number; reviewer_cases: number; blocked_cases: number; oldest_case_hours: number }[];
  unassigned_cases: number };

export default function AdminPage() {
  const { me, hasRole } = useStaff();
  const isAdmin = hasRole("admin");
  const staff = usePoll<StaffList>(isAdmin ? "/v1/staff/admin/staff" : null, 0);
  const load = usePoll<Workload>(isAdmin || hasRole("case_manager") ? "/v1/staff/admin/workload" : null, 15000);
  const action = useStaffAction(() => { staff.refresh(); load.refresh(); });

  if (!me) return <LoadingState label="Loading…" />;
  if (!isAdmin && !hasRole("case_manager")) {
    return <Notice tone="warn">Administration is available to AssureOps admins and case managers.</Notice>;
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-5">
      <PageHeader title="Administration" subtitle="Staff permissions and case workload. Metadata only: no customer content is shown here." />
      <ActionError error={action.error} />
      <ActionDone message={action.done} />

      <InquiriesCard />

      <Card>
        <CardHeader title="Workload" icon={<Gauge className="size-4" aria-hidden />}
          count={load.data ? `${load.data.unassigned_cases} case${load.data.unassigned_cases === 1 ? "" : "s"} without an analyst` : undefined} />
        <ApiErrorBanner error={load.error} />
        {load.data && (
          <TableWrap minWidth="min-w-[640px]">
            <thead><tr><Th>Staff member</Th><Th>Roles</Th><Th>As analyst</Th><Th>As reviewer</Th><Th>Blocked</Th><Th>Oldest case</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {load.data.staff.map((r) => (
                <tr key={r.user}>
                  <Td><p>{r.name}</p><Mono>{r.user}</Mono></Td>
                  <Td className="text-xs">{r.roles.map((x) => ROLE_LABEL[x] ?? x).join(", ") || "none"}</Td>
                  <Td>{r.analyst_cases}</Td>
                  <Td>{r.reviewer_cases}</Td>
                  <Td>{r.blocked_cases}</Td>
                  <Td className="text-xs">{r.oldest_case_hours ? `${r.oldest_case_hours} h` : "-"}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>

      {isAdmin ? (
        <Card>
          <CardHeader title="Staff roles" icon={<UsersRound className="size-4" aria-hidden />} count={staff.data ? `${staff.data.staff.length} staff` : undefined} />
          <ApiErrorBanner error={staff.error} />
          <p className="-mt-1 px-5 pb-3 text-xs text-muted">
            Another admin grants and revokes roles; nobody changes their own. Revoking analyst or senior reviewer ends that person&apos;s matching case duties at once.
          </p>
          {staff.data && (
            <TableWrap minWidth="min-w-[860px]">
              <thead><tr><Th>Staff member</Th>{staff.data.assignable_roles.map((r) => <Th key={r}>{ROLE_LABEL[r] ?? r}</Th>)}<Th>Last change</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {staff.data.staff.map((row) => {
                  const last = [...row.history].sort((a, b) => Math.max(b.granted_at ?? 0, b.revoked_at ?? 0) - Math.max(a.granted_at ?? 0, a.revoked_at ?? 0))[0];
                  const self = row.user === me.user;
                  return (
                    <tr key={row.user}>
                      <Td><p>{row.name}</p><Mono>{row.user}</Mono></Td>
                      {staff.data!.assignable_roles.map((role) => {
                        const has = row.roles.includes(role);
                        const key = `${row.user}-${role}`;
                        return (
                          <Td key={role}>
                            <Button variant={has ? "primary" : "secondary"} className="px-2 py-1 text-xs" disabled={self || action.busy !== null}
                              pressed={has} ariaLabel={`${has ? "Revoke" : "Grant"} ${ROLE_LABEL[role] ?? role} for ${row.user}`}
                              onClick={() => action.run(key, () => (has ? del : put)(`/v1/staff/admin/staff/${encodeURIComponent(row.user)}/roles/${role}`),
                                `${has ? "Revoked" : "Granted"} ${ROLE_LABEL[role] ?? role} for ${row.user}.`)}>
                              {action.busy === key ? "Saving…" : has ? "Held" : "Grant"}
                            </Button>
                          </Td>
                        );
                      })}
                      <Td className="text-xs text-muted">
                        {last ? (() => {
                          const at = last.active ? last.granted_at : last.revoked_at;
                          return `${last.active ? "granted" : "revoked"} ${last.role} by ${(last.active ? last.granted_by : last.revoked_by) ?? "seed"}${at ? ` · ${formatTime(at)}` : ""}`;
                        })() : "-"}
                        {self && <p>Your own roles are changed by another admin.</p>}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </TableWrap>
          )}
        </Card>
      ) : (
        <Notice tone="info"><ShieldPlus className="mr-1 inline size-4" aria-hidden />Only AssureOps admins change staff roles.</Notice>
      )}
    </div>
  );
}
