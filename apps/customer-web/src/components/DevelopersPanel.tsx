"use client";

import { pathFor, type RequestBody } from "@assureops/ui/api/contract";
import { api, del, put, useAction, usePoll } from "@assureops/ui/client";
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Field, Mono, Notice, StatusBadge, TableWrap, Td, Th, inputClass } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { UserCheck, UserMinus } from "lucide-react";
import { useEffect, useState } from "react";
import type { Settings } from "@/lib/types";

type Assignment = { user: string; display_name: string; granted_by: string; granted_at: number; expires_at: number | null;
  revoked_at: number | null; revoked_by: string | null; active: boolean };

/** Who may change this application: owners always; developers only while assigned here. */
export function DevelopersPanel({ appId }: { appId: string }) {
  const list = usePoll<Assignment[]>(`/v1/applications/${appId}/developers`, 0);
  const action = useAction();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [user, setUser] = useState("");
  const [days, setDays] = useState("");
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => { api<Settings>("/v1/settings").then(setSettings).catch(() => setSettings(null)); }, []);
  const isOwner = settings?.your_role === "owner";
  const active = (list.data ?? []).filter((a) => a.active);
  const candidates = (settings?.members ?? []).filter((m) => m.role === "developer" && !active.some((a) => a.user === m.user));
  const after = (message: string) => () => { setDone(message); list.refresh(); };

  return (
    <Card className="p-5">
      <CardHeader title="Assigned developers" icon={<UserCheck className="size-4" aria-hidden />} count={`${active.length}`} />
      {active.length === 0 ? (
        <EmptyState title="No developer assigned" body="Owners can still change this application. Assign a developer to let them connect it, submit releases and request retests." />
      ) : (
        <div className="mt-3 overflow-hidden rounded-lg border border-line">
          <TableWrap minWidth="min-w-[480px]">
            <thead><tr><Th>Developer</Th><Th>Assigned by</Th><Th>Expires</Th>{isOwner && <Th><span className="sr-only">Actions</span></Th>}</tr></thead>
            <tbody className="divide-y divide-line">
              {active.map((a) => (
                <tr key={a.user}>
                  <Td><p>{a.display_name}</p><Mono>{a.user}</Mono></Td>
                  <Td className="text-xs"><p>{a.granted_by}</p><p className="text-muted">{formatTime(a.granted_at)}</p></Td>
                  <Td className="text-xs">{a.expires_at ? formatTime(a.expires_at) : <StatusBadge status="unknown" label="no expiry" />}</Td>
                  {isOwner && (
                    <Td className="text-right">
                      <Button variant="danger" className="px-2 py-1 text-xs" disabled={action.busy !== null}
                        onClick={() => action.run(`un-${a.user}`, () => del(`/v1/applications/${appId}/developers/${encodeURIComponent(a.user)}`),
                          after(`${a.user} is no longer assigned.`))}>
                        <UserMinus className="size-3" aria-hidden /> Unassign
                      </Button>
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </TableWrap>
        </div>
      )}
      {isOwner && (
        <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={(e) => {
          e.preventDefault();
          const expires = days ? Date.now() / 1000 + Number(days) * 86400 : null;
          const body: RequestBody<"/v1/applications/{application_id}/developers/{username}", "put"> = { expires_at: expires };
          action.run("assign", () => put(pathFor("/v1/applications/{application_id}/developers/{username}", { application_id: appId, username: user }), body),
            () => { setUser(""); setDays(""); after(`Assigned ${user}.`)(); });
        }}>
          <Field label="Developer">
            <select required value={user} onChange={(e) => setUser(e.target.value)} className={`${inputClass} w-64`}>
              <option value="">Choose a developer…</option>
              {candidates.map((m) => <option key={m.user} value={m.user}>{m.name} ({m.user})</option>)}
            </select>
          </Field>
          <Field label="Expires after (days, optional)">
            <input type="number" min={1} max={365} value={days} onChange={(e) => setDays(e.target.value)} className={`${inputClass} w-40`} />
          </Field>
          <Button type="submit" variant="primary" disabled={action.busy !== null || !user}>{action.busy === "assign" ? "Assigning…" : "Assign"}</Button>
        </form>
      )}
      {action.error && <div className="mt-3"><ErrorBanner message={action.error} /></div>}
      {done && <div className="mt-3"><Notice tone="success">{done}</Notice></div>}
    </Card>
  );
}
