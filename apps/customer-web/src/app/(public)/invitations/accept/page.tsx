"use client";

import { post, useAction } from "@assureops/ui/client";
import { Button, Card, ErrorBanner, Notice, PageHeader } from "@assureops/ui/components";
import { MailCheck } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

function Accept() {
  const token = useSearchParams().get("token") ?? "";
  const action = useAction();
  const [joined, setJoined] = useState<{ workspace_id: string; role: string } | null>(null);

  if (!token) return <Notice tone="warn">This invitation link has no token. Open the link from your invitation e-mail again.</Notice>;
  return (
    <Card className="p-6">
      <div className="flex items-start gap-3">
        <MailCheck className="mt-0.5 size-5 text-brand-700" aria-hidden />
        <div className="space-y-3">
          <p className="text-sm">
            Accepting adds you to the workspace with the role your invitation names. The invitation works once, only for the e-mail address it
            was sent to, and expires after 7 days. You may be asked to sign in first.
          </p>
          {joined ? (
            <Notice tone="success">
              You joined workspace <strong>{joined.workspace_id}</strong> as <strong>{joined.role}</strong>. <a className="font-medium underline" href="/overview">Open the portal</a>
            </Notice>
          ) : (
            <Button variant="primary" disabled={action.busy !== null}
              onClick={() => action.run("accept", () => post<{ workspace_id: string; role: string }>("/v1/invitations/accept", { token })).then((r) => r && setJoined(r))}>
              {action.busy ? "Accepting…" : "Accept invitation"}
            </Button>
          )}
          {action.error && <ErrorBanner message={action.error} />}
        </div>
      </div>
    </Card>
  );
}

export default function AcceptInvitationPage() {
  return (
    <div className="mx-auto max-w-xl space-y-5">
      <PageHeader title="Join an AssureOps workspace" subtitle="Accept the invitation you received by e-mail." />
      <Suspense fallback={null}><Accept /></Suspense>
    </div>
  );
}
