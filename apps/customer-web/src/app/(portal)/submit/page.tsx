"use client";

import { post, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, ErrorBanner, Field, Notice, StatusBadge, inputClass } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { GitBranch, Send } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PageTop, WithSuspense } from "@/components/bits";
import { useApp } from "@/lib/app-context";

type Submission = { case_id: string; application_id: string; name: string; environment: string; url: string; repository: string | null;
  state: string; submitted_at: number; report_id: string | null };

const STAGE: Record<string, string> = {
  submitted: "Waiting for AssureOps to assign a developer", triage: "Being planned by AssureOps", assessment: "Being tested",
  awaiting_customer: "AssureOps needs something from you (open the case)", review: "Result waiting for admin approval",
  published: "Result published", monitoring: "Result published", reassessment: "Retesting a new release",
};

const EMPTY = { name: "", purpose: "", repository: "", base_url: "", environment: "staging", chat_path: "/chat", reply_field: "reply",
  test_token: "", health_path: "/health", manifest_path: "/manifest" };

function SubmitView() {
  const { me } = useApp();
  const owner = me?.role === "owner";
  const list = usePoll<Submission[]>("/v1/submissions", 15000);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ case_id: string } | null>(null);
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const ready = form.name.trim().length >= 3 && form.purpose.trim().length >= 10 && form.repository.trim() && form.base_url.trim();

  const submit = async () => {
    setBusy(true); setError(null); setDone(null);
    try {
      const body = { ...form, chat_path: form.chat_path.trim() || null, test_token: form.test_token.trim() || null };
      setDone(await post<{ case_id: string }>("/v1/submissions", body));
      setForm(EMPTY);
      list.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1100px] space-y-5">
      <PageTop eyebrow="Test an application" title="Submit your AI application for testing"
        subtitle="Give its GitHub link and the address where it runs. An AssureOps developer tests it, an AssureOps admin approves the result, and you receive the report here and under Reports." />

      {owner ? (
        <Card className="p-5">
          <CardHeader title="Application" icon={<Send className="size-4" aria-hidden />} />
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <Field label="Name"><input className={inputClass} value={form.name} onChange={set("name")} placeholder="Support Bot" /></Field>
            <Field label="Environment to test" hint="Test a staging copy where possible; production tests send real requests.">
              <select className={inputClass} value={form.environment} onChange={set("environment")}>
                <option value="staging">staging</option><option value="production">production</option>
              </select></Field>
            <Field label="GitHub repository" hint="https://github.com/owner/name or owner/name">
              <input className={inputClass} value={form.repository} onChange={set("repository")} placeholder="https://github.com/acme/support-bot" /></Field>
            <Field label="Live URL" hint="Where the application runs, without a path (it must answer GET /health and /manifest)">
              <input className={inputClass} value={form.base_url} onChange={set("base_url")} placeholder="https://staging.support-bot.example" /></Field>
            <div className="md:col-span-2"><Field label="What does it do?">
              <textarea className={`${inputClass} h-20`} value={form.purpose} onChange={set("purpose")}
                placeholder="Answers billing questions for signed-in customers; never shows another customer's invoices." /></Field></div>
            <Field label="Chat endpoint (optional)" hint="The path that takes a user message, e.g. /chat">
              <input className={inputClass} value={form.chat_path} onChange={set("chat_path")} /></Field>
            <Field label="Reply field" hint="Where the answer is in the JSON response">
              <input className={inputClass} value={form.reply_field} onChange={set("reply_field")} /></Field>
            <div className="md:col-span-2"><Field label="Test account token (optional)"
              hint="A bearer token of a synthetic test account. Stored encrypted and never shown again. Never a real customer's account.">
              <input type="password" autoComplete="off" className={inputClass} value={form.test_token} onChange={set("test_token")} /></Field></div>
          </div>
          <details className="mt-3 text-sm"><summary className="cursor-pointer text-muted">Advanced paths</summary>
            <div className="mt-2 grid gap-3 md:grid-cols-2">
              <Field label="Health path"><input className={inputClass} value={form.health_path} onChange={set("health_path")} /></Field>
              <Field label="Manifest path"><input className={inputClass} value={form.manifest_path} onChange={set("manifest_path")} /></Field>
            </div></details>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button variant="primary" disabled={busy || !ready} onClick={submit}><Send className="size-4" aria-hidden /> {busy ? "Submitting…" : "Submit for testing"}</Button>
          </div>
          {error && <div className="mt-3"><ErrorBanner message={error} /></div>}
          {done && <div className="mt-3"><Notice tone="success">Submitted. AssureOps has been notified; follow the progress below or on the{" "}
            <Link className="underline" href={`/cases/${done.case_id}`}>case page</Link>.</Notice></div>}
        </Card>
      ) : <Notice tone="info">Only the workspace owner submits applications. You can follow their progress below.</Notice>}

      <Card className="p-5">
        <CardHeader title="Your submissions" icon={<GitBranch className="size-4" aria-hidden />} count={`${list.data?.length ?? 0}`} />
        <ApiErrorBanner error={list.error} />
        {list.data?.length === 0 && <EmptyState title="Nothing submitted yet" body="Submit an application above to have it tested." />}
        <ul className="mt-3 space-y-3">
          {list.data?.map((s) => (
            <li key={s.case_id} className="rounded-lg border border-line p-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{s.name}</span>
                <StatusBadge status={s.report_id ? "supported" : "pending"} label={STAGE[s.state] ?? s.state} />
                <span className="text-xs text-muted">{s.environment} · {s.url}{s.repository ? ` · github.com/${s.repository}` : ""} · {formatTime(s.submitted_at)}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-3 text-xs">
                <Link className="text-brand-700 underline" href={`/cases/${s.case_id}`}>Case and messages</Link>
                {s.report_id && <Link className="font-medium text-brand-700 underline" href={`/reports/${s.report_id}`}>Open the result</Link>}
              </div>
            </li>))}
        </ul>
      </Card>
    </div>
  );
}

export default function SubmitPage() {
  return <WithSuspense label="Loading…"><SubmitView /></WithSuspense>;
}
