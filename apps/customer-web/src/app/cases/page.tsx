"use client";

import { post, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, Field, inputClass, LoadingState, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { FolderPlus, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { PageTop } from "@/components/bits";
import { useApp } from "@/lib/app-context";
import type { AssessmentCase } from "@/lib/types";

function SubmitCase({ onDone }: { onDone: () => void }) {
  const { applications, applicationId } = useApp();
  const router = useRouter();
  const [app, setApp] = useState("");
  const [title, setTitle] = useState("");
  const [scope, setScope] = useState("");
  const { busy, error, run } = useAction();
  const target = app || applicationId || "";

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run("submit", async () => {
      const created = await post<AssessmentCase>("/v1/customer/cases", { application_id: target, title: title.trim(), scope_note: scope.trim() });
      router.push(`/cases/${created.id}`);
    }, onDone);
  };

  return (
    <form onSubmit={submit} className="space-y-3 px-5 pb-5">
      <Field label="Application">
        <select className={inputClass} value={target} onChange={(e) => setApp(e.target.value)} required>
          {applications.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </Field>
      <Field label="Title"><input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} minLength={3} required /></Field>
      <Field label="Scope note" hint="What should be assessed: release, environment, workflows in scope, anything out of scope.">
        <textarea className={inputClass} rows={4} value={scope} onChange={(e) => setScope(e.target.value)} minLength={3} required />
      </Field>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <Button type="submit" variant="primary" disabled={!!busy || !target || title.trim().length < 3 || scope.trim().length < 3}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <FolderPlus className="size-4" aria-hidden />} Submit case
      </Button>
    </form>
  );
}

export default function CasesPage() {
  const { applications, canWrite } = useApp();
  const { data, error, loading, refresh } = usePoll<AssessmentCase[]>("/v1/customer/cases", 10000);

  if (loading && !data) return <LoadingState label="Loading cases…" />;
  const name = (id: string) => applications.find((a) => a.id === id)?.name ?? id;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Assessment Cases" title="Assessment cases" subtitle="A case is your two-way workspace with the AssureOps assessment team: scope, evidence requests, messages and published reports." />
      <ApiErrorBanner error={error} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Cases" count={data ? `${data.length}` : undefined} />
          {!data ? null : data.length === 0 ? <EmptyState title="No cases yet" body="Submit a case to request an assessment of one of your applications." /> : (
            <TableWrap minWidth="min-w-[640px]">
              <thead><tr><Th>Case</Th><Th>Application</Th><Th>State</Th><Th>Requests</Th><Th>Updated</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.map((c) => {
                  const open = c.evidence_requests.filter((r) => r.state === "open").length;
                  return (
                    <tr key={c.id}>
                      <Td><Link href={`/cases/${c.id}`} className="font-medium hover:underline">{c.title}</Link><span className="block text-xs text-muted">Opened by {c.created_by} · {formatTime(c.created_at)}</span></Td>
                      <Td>{name(c.application_id)}</Td>
                      <Td><StatusBadge status={c.state} /></Td>
                      <Td className="text-xs">{open ? <span className="font-medium text-amber-700">{open} awaiting your response</span> : <span className="text-muted">None open</span>}</Td>
                      <Td className="whitespace-nowrap text-muted">{formatTime(c.updated_at)}</Td>
                    </tr>
                  );
                })}
              </tbody>
            </TableWrap>
          )}
        </Card>
        <Card>
          <CardHeader title="Submit a case" icon={<FolderPlus className="size-4" aria-hidden />} />
          {canWrite ? <SubmitCase onDone={refresh} /> : <p className="px-5 pb-5 text-sm text-muted">Only owners and developers can submit cases.</p>}
        </Card>
      </div>
    </div>
  );
}
