"use client";

import { Bell, CheckCheck } from "lucide-react";
import { post, usePoll } from "./client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, LoadingState, PageHeader, StatusBadge } from "./components";
import { formatTime, timeAgo } from "./format";

export type InboxItem = { id: string; kind: string; subject: string; body: string; workspace_id: string | null; created_at: number;
  read_at: number | null; delivery: string };
export type Inbox = { unread: number; items: InboxItem[] };

/** Unread count for the top bar; polls the portal's own inbox route. */
export function useUnread(path: string): number {
  const { data } = usePoll<Inbox>(path, 30000);
  return data?.unread ?? 0;
}

/** Notifications addressed to the signed-in person. Delivery by e-mail or webhook is tracked separately from reading here. */
export function InboxPage({ path }: { path: string }) {
  const { data, error, loading, refresh } = usePoll<Inbox>(path, 15000);
  if (loading && !data) return <LoadingState label="Loading notifications…" />;
  return (
    <div className="mx-auto max-w-[1000px] space-y-5">
      <PageHeader title="Notifications" subtitle="Messages addressed to you. Notifications never grant access; links still require your own permissions." />
      <ApiErrorBanner error={error} />
      <Card>
        <CardHeader title="Inbox" icon={<Bell className="size-4" aria-hidden />} count={data ? `${data.unread} unread` : undefined}
          action={data && data.unread > 0 ? (
            <Button className="px-2 py-1 text-xs" onClick={() => post(`${path}/read-all`).then(refresh)}>
              <CheckCheck className="size-3" aria-hidden /> Mark all read
            </Button>
          ) : undefined} />
        {!data || data.items.length === 0 ? (
          <div className="p-5"><EmptyState title="No notifications" body="Invitations, assignments and role changes addressed to you appear here." /></div>
        ) : (
          <ul className="divide-y divide-line">
            {data.items.map((n) => (
              <li key={n.id} className={`px-5 py-4 ${n.read_at ? "" : "bg-brand-50/40"}`}>
                <div className="flex flex-wrap items-center gap-2">
                  {!n.read_at && <span className="size-2 rounded-full bg-brand-600" aria-label="unread" />}
                  <h3 className="text-sm font-semibold">{n.subject}</h3>
                  <StatusBadge status="unknown" label={n.kind.replaceAll("_", " ")} />
                  <span className="text-xs text-muted" title={formatTime(n.created_at)}>{timeAgo(n.created_at)}</span>
                </div>
                <p className="mt-1 text-sm whitespace-pre-line text-muted">{n.body}</p>
                {!n.read_at && (
                  <button type="button" className="mt-2 text-xs font-medium text-brand-700 underline-offset-2 hover:underline"
                    onClick={() => post(`${path}/${n.id}/read`).then(refresh)}>
                    Mark as read
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
