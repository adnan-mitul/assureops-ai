"use client";

import { pathFor, type RequestBody } from "@assureops/ui/api/contract";
import { post, put, useAction, usePoll } from "@assureops/ui/client";
import { Button, Card, CardHeader, ErrorBanner, Field, Mono, Notice, StatusBadge, TableWrap, Td, Th, inputClass } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { MailPlus, Users, X } from "lucide-react";
import { useState } from "react";

type Member = { user: string; name: string; role: string };
type Invitation = { id: string; email: string; role: string; invited_by: string; expires_at: number; accepted_at: number | null; revoked_at: number | null };
const ROLES = ["owner", "developer", "reviewer", "viewer"] as const;

function invitationState(i: Invitation): string {
  if (i.accepted_at) return "accepted";
  if (i.revoked_at) return "revoked";
  return i.expires_at * 1000 < Date.now() ? "expired" : "open";
}

/** Owners invite people, change roles and remove access; everyone else sees the member list read-only. */
export function MembersPanel({ members, isOwner, you, onChanged }: { members: Member[]; isOwner: boolean; you: string; onChanged: () => void }) {
  const invitations = usePoll<Invitation[]>(isOwner ? "/v1/invitations" : null, 0);
  const action = useAction();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<(typeof ROLES)[number]>("developer");
  const [done, setDone] = useState<string | null>(null);
  const after = (message: string) => () => { setDone(message); onChanged(); invitations.refresh(); };

  return (
    <Card>
      <CardHeader title="Members" icon={<Users className="size-4" aria-hidden />} count={`${members.length}`} />
      <TableWrap minWidth="min-w-[600px]">
        <thead><tr><Th>Name</Th><Th>User</Th><Th>Role</Th>{isOwner && <Th><span className="sr-only">Actions</span></Th>}</tr></thead>
        <tbody className="divide-y divide-line">
          {members.map((m) => (
            <tr key={m.user}>
              <Td>{m.name}</Td>
              <Td><Mono>{m.user}</Mono></Td>
              <Td>
                {isOwner && m.user !== you ? (
                  <select aria-label={`Role for ${m.user}`} value={m.role} disabled={action.busy !== null} className={`${inputClass} w-40 min-w-40 py-1 capitalize`}
                    onChange={(e) => {
                      const role = e.target.value;
                      // A role change takes effect on the member's next request; confirm so a stray selection cannot promote anyone.
                      if (!window.confirm(`Change ${m.user} from ${m.role} to ${role}?`)) return;
                      action.run(`role-${m.user}`, () => put(`/v1/members/${encodeURIComponent(m.user)}`, { role }), after(`${m.user} is now ${role}.`));
                    }}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                ) : <span className="capitalize">{m.role}</span>}
              </Td>
              {isOwner && (
                <Td className="text-right">
                  {m.user !== you && (
                    <Button variant="danger" className="px-2 py-1 text-xs" disabled={action.busy !== null}
                      onClick={() => window.confirm(`Remove ${m.user} from this workspace? Their next request is refused.`) &&
                        action.run(`remove-${m.user}`, () => put(`/v1/members/${encodeURIComponent(m.user)}`, { role: null }), after(`Removed ${m.user}.`))}>
                      <X className="size-3" aria-hidden /> Remove
                    </Button>
                  )}
                </Td>
              )}
            </tr>
          ))}
        </tbody>
      </TableWrap>
      <p className="px-5 py-3 text-xs text-muted">
        Owners change every application; developers change only the applications they are assigned to; reviewers approve; viewers read only.
      </p>

      {isOwner && (
        <div className="space-y-4 border-t border-line px-5 py-4">
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => {
            e.preventDefault();
            const body: RequestBody<"/v1/invitations", "post"> = { email: email.trim(), role };
            action.run("invite", () => post(pathFor("/v1/invitations"), body), () => { setEmail(""); after(`Invitation sent to ${email.trim()}.`)(); });
          }}>
            <Field label="Invite by e-mail">
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={`${inputClass} w-64`} placeholder="name@company.com" />
            </Field>
            <Field label="Role">
              <select value={role} onChange={(e) => setRole(e.target.value as (typeof ROLES)[number])} className={`${inputClass} w-36 capitalize`}>
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </Field>
            <Button type="submit" variant="primary" disabled={action.busy !== null || !email.trim()}>
              <MailPlus className="size-4" aria-hidden /> {action.busy === "invite" ? "Sending…" : "Invite"}
            </Button>
          </form>
          {action.error && <ErrorBanner message={action.error} />}
          {done && <Notice tone="success">{done}</Notice>}
          {(invitations.data?.length ?? 0) > 0 && (
            <div className="overflow-hidden rounded-lg border border-line">
              <TableWrap minWidth="min-w-[520px]">
                <thead><tr><Th>Invitation</Th><Th>Role</Th><Th>State</Th><Th>Expires</Th><Th><span className="sr-only">Actions</span></Th></tr></thead>
                <tbody className="divide-y divide-line">
                  {invitations.data!.map((i) => {
                    const state = invitationState(i);
                    return (
                      <tr key={i.id}>
                        <Td><Mono>{i.email}</Mono></Td>
                        <Td className="capitalize">{i.role}</Td>
                        <Td><StatusBadge status={state === "open" ? "pending" : state === "accepted" ? "accepted" : state === "revoked" ? "withdrawn" : "unknown"} label={state} /></Td>
                        <Td className="text-xs text-muted">{formatTime(i.expires_at)}</Td>
                        <Td className="text-right">
                          {state === "open" && (
                            <Button variant="danger" className="px-2 py-1 text-xs" disabled={action.busy !== null}
                              onClick={() => action.run(`revoke-${i.id}`, () => post(`/v1/invitations/${i.id}/revoke`), after(`Revoked the invitation to ${i.email}.`))}>
                              Revoke
                            </Button>
                          )}
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableWrap>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
