"use client";

import { post, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, ErrorBanner, Field, inputClass, LoadingState } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { Megaphone } from "lucide-react";
import { useState } from "react";
import { PageTop, useRouteId, WithSuspense } from "@/components/bits";
import { useApp } from "@/lib/app-context";

type Notice = { id: string; kind: "notice" | "change"; author: string; subject: string; body: string; created_at: number };

function NoticesView() {
  const appId = useRouteId();
  const base = `/v1/applications/${encodeURIComponent(appId)}/notices`;
  const { canWrite, canReview } = useApp();
  const notices = usePoll<Notice[]>(base, 15000);
  const action = useAction();
  const [draft, setDraft] = useState({ subject: "", body: "" });

  if (notices.loading && !notices.data) return <LoadingState label="Loading notices…" />;

  return (
    <div className="mx-auto max-w-[1100px] space-y-5">
      <PageTop eyebrow="Applications · Notice board" title={`Notice board for ${appId}`}
        subtitle="Changes to this application and posts from its team. Owners, reviewers and assigned developers are notified in the portal, by e-mail and by webhook." />
      <ApiErrorBanner error={notices.error} />
      {action.error && <ErrorBanner message={action.error} />}

      {(canWrite || canReview) && (
        <Card className="p-5">
          <CardHeader title="Post a notice" icon={<Megaphone className="size-4" aria-hidden />} />
          <div className="mt-3 space-y-2">
            <Field label="Subject"><input className={inputClass} value={draft.subject} maxLength={200}
              onChange={(e) => setDraft({ ...draft, subject: e.target.value })} /></Field>
            <Field label="Message"><textarea className={`${inputClass} h-24`} value={draft.body} maxLength={4000}
              onChange={(e) => setDraft({ ...draft, body: e.target.value })} /></Field>
            <Button variant="primary" disabled={!!action.busy || draft.subject.trim().length < 3 || !draft.body.trim()}
              onClick={() => action.run("post", () => post(base, draft), () => { setDraft({ subject: "", body: "" }); notices.refresh(); })}>
              Post and notify the team
            </Button>
          </div>
        </Card>)}

      <Card className="p-5">
        <CardHeader title="Notices" icon={<Megaphone className="size-4" aria-hidden />} count={`${notices.data?.length ?? 0}`} />
        {notices.data?.length === 0 && <EmptyState title="No notices yet" body="Releases, profile proposals, AI reviews and finished assessments appear here automatically." />}
        <ul className="mt-3 space-y-3">
          {notices.data?.map((n) => (
            <li key={n.id} className="rounded-lg border border-line p-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${n.kind === "change" ? "bg-sky-50 text-sky-700" : "bg-gray-100 text-gray-700"}`}>
                  {n.kind === "change" ? "Change" : "Team notice"}</span>
                <span className="font-semibold">{n.subject}</span>
                <span className="text-xs text-muted">{n.author} · {formatTime(n.created_at)}</span>
              </div>
              <p className="mt-2 whitespace-pre-wrap text-muted">{n.body}</p>
            </li>))}
        </ul>
      </Card>
    </div>
  );
}

export default function NoticesPage() {
  return <WithSuspense label="Loading notices…"><NoticesView /></WithSuspense>;
}
