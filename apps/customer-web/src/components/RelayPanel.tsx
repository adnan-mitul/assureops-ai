"use client";

import { post, useAction, usePoll } from "@assureops/ui/client";
import { Button, Card, CardHeader, ErrorBanner, Mono, Notice, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { Network } from "lucide-react";
import { useState } from "react";
import { useApp } from "@/lib/app-context";

type Listing = {
  credentials: { id: string; environment: string; revoked: boolean }[];
  recent_tasks: { id: string; kind: string; status: string; created_at: number; completed_at: number | null; error: string | null }[];
};

const TASK_STATUS: Record<string, string> = { queued: "queued", claimed: "running", completed: "completed", expired: "error", cancelled: "cancelled" };

/** Private connector: for targets the hosted service cannot reach. The relay connects outbound only. */
export function RelayPanel({ appId }: { appId: string }) {
  const { me } = useApp();
  const list = usePoll<Listing>(`/v1/applications/${appId}/relay-credentials`, 15000);
  const action = useAction();
  const [token, setToken] = useState<string | null>(null);
  const isOwner = me?.role === "owner";
  const active = (list.data?.credentials ?? []).filter((c) => !c.revoked);

  return (
    <Card className="p-5">
      <CardHeader title="Private connector (relay)" icon={<Network className="size-4" aria-hidden />} count={`${active.length} active`} />
      <p className="text-sm text-muted">
        For a target inside your network: set <Mono>{`"execution": {"mode": "relay"}`}</Mono> in the connection settings and run
        <Mono> python -m assureops_connectors.relay --api &lt;AssureOps URL&gt; --token-file &lt;file&gt;</Mono> next to the target. The relay only
        connects outbound, runs one frozen test at a time in a scrubbed sandbox and returns results; a missed deadline is an error, never a pass.
      </p>
      {token && (
        <div className="mt-3"><Notice tone="warn">Copy this relay token into the relay&apos;s secret store now; it is not shown again: <Mono>{token}</Mono></Notice></div>
      )}
      {isOwner && (
        <div className="mt-3">
          <Button variant="primary" disabled={action.busy !== null}
            onClick={() => action.run("issue", () => post<{ token: string }>(`/v1/applications/${appId}/relay-credentials`, { environment: "staging" }),
              ).then((r) => { if (r) { setToken(r.token); list.refresh(); } })}>
            {action.busy === "issue" ? "Issuing…" : "Issue relay credential"}
          </Button>
        </div>
      )}
      {active.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {active.map((c) => (
            <li key={c.id} className="flex items-center gap-2">
              <Mono>{c.id}</Mono><span className="text-xs text-muted">{c.environment}</span>
              {isOwner && (
                <Button variant="danger" className="px-2 py-1 text-xs" disabled={action.busy !== null}
                  onClick={() => action.run(`rv-${c.id}`, () => post(`/v1/applications/${appId}/relay-credentials/${c.id}/revoke`), list.refresh)}>
                  Revoke
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {(list.data?.recent_tasks.length ?? 0) > 0 && (
        <div className="mt-4 overflow-hidden rounded-lg border border-line">
          <TableWrap minWidth="min-w-[520px]" label="Recent relay tasks">
            <thead><tr><Th>Task</Th><Th>Kind</Th><Th>Status</Th><Th>Queued</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {list.data!.recent_tasks.map((t) => (
                <tr key={t.id}>
                  <Td><Mono>{t.id}</Mono>{t.error && <p className="text-xs text-muted">{t.error}</p>}</Td>
                  <Td>{t.kind}</Td>
                  <Td><StatusBadge status={TASK_STATUS[t.status] ?? "unknown"} label={t.status} /></Td>
                  <Td className="text-xs">{formatTime(t.created_at)}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        </div>
      )}
      {action.error && <div className="mt-3"><ErrorBanner message={action.error} /></div>}
    </Card>
  );
}
