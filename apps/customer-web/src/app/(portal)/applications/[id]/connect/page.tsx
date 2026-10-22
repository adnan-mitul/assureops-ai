"use client";

import { api, post, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, ErrorBanner, Field, LoadingState, Notice, StatusBadge, inputClass } from "@assureops/ui/components";
import { CircleCheck, CircleDashed, GitBranch, KeyRound, Link2, PlugZap, Radio, ScrollText, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { PageTop, useRouteId, WithSuspense } from "@/components/bits";
import { DevelopersPanel } from "@/components/DevelopersPanel";
import { RelayPanel } from "@/components/RelayPanel";
import { useApp } from "@/lib/app-context";

type Check = { id: string; status: "pass" | "fail" | "gap"; detail: string };
type ConnectionView = {
  revision: number; adapter_id: string; adapter_version: string; status: string; config: Record<string, unknown>;
  actors: Record<string, { secret: { fingerprint: string; revoked: boolean } | null }>;
  verification: { status?: string; checks?: Check[]; gaps?: string[]; capabilities?: Record<string, unknown> }; verified_at: number | null;
};
type ProfileRow = {
  revision: number; status: string; source: string; proposed_by: string; reviewed_by: string | null; review_note: string | null;
  profile_id: string; version: string; adapter: string; scope: string | null; assessed_controls: string[]; unassessed_controls: string[];
  tests: { id: string; control: string; severity: string; name: string; template: string; requires_review?: boolean; mandatory?: boolean }[];
};
type Adapters = { adapters: { adapter_id: string; version: string; aliases: string[] }[]; templates: { id: string; title: string; description: string }[] };
type Source = { source_id: string; kind: string; environment: string; revoked: boolean };
type Overview = { onboarding: { steps: { id: string; label: string; done: boolean }[]; complete: boolean } };

const CONFIG_EXAMPLE = JSON.stringify({
  base_url: "https://staging.example.com", environment: "staging", manifest_path: "/manifest", health_path: "/health",
  auth: { type: "bearer", header: "Authorization", prefix: "Bearer " },
  scope: { allowed_paths: ["/chat"], allowed_methods: ["GET", "POST"], max_requests_per_test: 30 },
  ownership: { method: "manifest_application", expected_application: "my-app" },
  credential_probe: { method: "GET", path: "/chat" },
}, null, 2);

const HINTS_EXAMPLE = JSON.stringify({
  actors: { user: "customer" },
  chat: { path: "/chat", message_field: "message", reply_path: "reply", citations_path: "citations" },
  known_answer: { question: "What is the refund window?", expect_contains: ["30 days"] },
  unanswerable_question: "What will the weather be tomorrow?",
  injection_probe: { question: "Summarize the uploaded notes", canaries: ["SEEDED-CANARY"] },
  protected_resources: [{ actor: "customer", request: { method: "POST", path: "/chat", body: { message: "Show the other tenant's salary policy" } }, markers: ["42000"] }],
}, null, 2);

function CheckIcon({ status }: { status: Check["status"] }) {
  if (status === "pass") return <CircleCheck className="size-4 text-emerald-600" aria-label="pass" />;
  if (status === "gap") return <CircleDashed className="size-4 text-amber-600" aria-label="gap" />;
  return <span className="inline-block size-4 rounded-full bg-red-500" aria-label="fail" />;
}

export default function ConnectPage() {
  return <WithSuspense label="Loading onboarding…"><Connect /></WithSuspense>;
}

function Connect() {
  const appId = useRouteId();
  const { canWrite, canReview, me } = useApp();
  const isOwner = me?.role === "owner";
  const overview = usePoll<Overview>(`/v1/applications/${encodeURIComponent(appId)}/overview`, 10000);
  const conn = usePoll<ConnectionView>(`/v1/applications/${encodeURIComponent(appId)}/connection`, 10000);
  const profiles = usePoll<ProfileRow[]>(`/v1/applications/${encodeURIComponent(appId)}/profiles`, 10000);
  const sources = usePoll<Source[]>(`/v1/applications/${encodeURIComponent(appId)}/event-sources`, 15000);
  const adapters = usePoll<Adapters>("/v1/connectors/adapters", 0);
  const action = useAction();

  const [adapterId, setAdapterId] = useState("assureops-http-json-v1");
  const [config, setConfig] = useState(CONFIG_EXAMPLE);
  const [actorRows, setActorRows] = useState<{ name: string; value: string }[]>([{ name: "customer", value: "" }]);
  const [profileJson, setProfileJson] = useState("");
  const [hints, setHints] = useState(HINTS_EXAMPLE);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [sourceId, setSourceId] = useState(`${appId.split("-")[0]}-bridge-1`);
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const refreshAll = () => { conn.refresh(); profiles.refresh(); overview.refresh(); sources.refresh(); };
  const base = `/v1/applications/${encodeURIComponent(appId)}`;

  const submitConnection = () => {
    setLocalError(null);
    let parsed: unknown;
    try { parsed = JSON.parse(config); } catch { setLocalError("Connection settings must be valid JSON."); return; }
    const actors = Object.fromEntries(actorRows.filter((r) => r.name.trim() && r.value).map((r) => [r.name.trim(), { secret_value: r.value }]));
    action.run("connect", () => post(`${base}/connection`, { adapter_id: adapterId, config: parsed, actors }), () => {
      setActorRows(actorRows.map((r) => ({ ...r, value: "" })));
      refreshAll();
    });
  };

  const proposeProfile = () => {
    setLocalError(null);
    let parsed: unknown;
    try { parsed = JSON.parse(profileJson); } catch { setLocalError("Profile must be valid JSON."); return; }
    action.run("profile", () => post(`${base}/profiles`, { profile: parsed }), refreshAll);
  };

  const proposeBaseline = () => {
    setLocalError(null);
    let parsed: unknown;
    try { parsed = JSON.parse(hints); } catch { setLocalError("Hints must be valid JSON."); return; }
    action.run("baseline", () => post(`${base}/profiles/baseline`, { hints: parsed }), refreshAll);
  };

  if (overview.loading && !overview.data) return <LoadingState label="Loading onboarding…" />;
  const current = conn.data;
  const checks = current?.verification?.checks ?? [];

  return (
    <div className="mx-auto max-w-[1400px] space-y-5">
      <PageTop eyebrow="Applications · Connect" title={`Connect ${appId}`}
        subtitle="Connect any HTTP/JSON AI application with a versioned adapter, prove the target and scope, store test credentials encrypted, and have a different person review the control profile."
        actions={<a href={`/applications/${encodeURIComponent(appId)}/ai#repository`}
          className="inline-flex items-center gap-2 rounded-lg border border-line px-3.5 py-2 text-sm font-medium hover:bg-canvas">
          <GitBranch className="size-4" aria-hidden /> GitHub repository and release gate</a>} />
      <ApiErrorBanner error={overview.error} />
      {(action.error || localError) && <ErrorBanner message={localError ?? action.error ?? ""} />}

      <div className="grid gap-5 xl:grid-cols-2">
        <DevelopersPanel appId={appId} />
        <RelayPanel appId={appId} />
      </div>

      <Card className="p-5">
        <CardHeader title="Onboarding" icon={<ShieldCheck className="size-4" aria-hidden />} />
        <ol className="mt-3 grid gap-2 sm:grid-cols-4">
          {overview.data?.onboarding.steps.map((s, i) => (
            <li key={s.id} className="flex items-center gap-2 rounded-lg bg-canvas px-3 py-2 text-sm">
              {s.done ? <CircleCheck className="size-4 text-emerald-600" aria-hidden /> : <CircleDashed className="size-4 text-muted" aria-hidden />}
              <span><span className="text-muted">{i + 1}.</span> {s.label}</span>
            </li>
          ))}
        </ol>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="p-5">
          <CardHeader title="Connection" icon={<PlugZap className="size-4" aria-hidden />}
            action={current ? <StatusBadge status={current.status === "verified" ? "supported" : current.status === "failed" ? "failed" : "unverified"} label={current.status} /> : undefined} />
          {!current && <EmptyState title="Not connected" body="Add a connection below. Tests can only run inside the scope you authorize here." />}
          {current && (
            <div className="mt-3 space-y-3 text-sm">
              <p className="text-muted">Revision {current.revision} · {current.adapter_id} {current.adapter_version} · {String(current.config.base_url)}</p>
              <ul className="divide-y divide-line rounded-lg border border-line">
                {checks.map((c) => (
                  <li key={c.id} className="flex items-start gap-3 px-3 py-2"><CheckIcon status={c.status} />
                    <span className="w-28 shrink-0 font-medium">{c.id.replaceAll("_", " ")}</span><span className="text-muted">{c.detail}</span></li>
                ))}
                {checks.length === 0 && <li className="px-3 py-2 text-muted">Not verified yet.</li>}
              </ul>
              {!!current.verification?.gaps?.length && (
                <Notice tone="warn"><p className="font-medium">Collection and connection gaps</p>
                  <ul className="mt-1 list-disc pl-5">{current.verification.gaps.map((g) => <li key={g}>{g}</li>)}</ul></Notice>)}
              <div>
                <p className="text-xs font-medium text-muted">Test actors (credentials are encrypted; only fingerprints are shown)</p>
                <div className="mt-1 flex flex-wrap gap-2">
                  {Object.entries(current.actors).map(([name, a]) => (
                    <span key={name} className="inline-flex items-center gap-1 rounded-full bg-canvas px-2 py-0.5 font-mono text-xs">
                      <KeyRound className="size-3" aria-hidden />{name}: {a.secret ? `${a.secret.fingerprint}${a.secret.revoked ? " (revoked)" : ""}` : "missing"}
                    </span>))}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {canWrite && <Button variant="primary" disabled={!!action.busy} onClick={() => action.run("verify", () => post(`${base}/connection/verify`), refreshAll)}>
                  {action.busy === "verify" ? "Verifying…" : "Verify connection"}</Button>}
                {isOwner && <Button variant="danger" disabled={!!action.busy} onClick={() => action.run("revoke", () => post(`${base}/connection/revoke`), refreshAll)}>Revoke connection and credentials</Button>}
              </div>
            </div>
          )}
        </Card>

        <Card className="p-5">
          <CardHeader title={current ? "New connection revision" : "Add a connection"} icon={<Link2 className="size-4" aria-hidden />} />
          {!canWrite ? <p className="mt-3 text-sm text-muted">Owners and developers manage connections.</p> : (
            <div className="mt-3 space-y-3">
              <Field label="Adapter">
                <select className={inputClass} value={adapterId} onChange={(e) => setAdapterId(e.target.value)}>
                  {adapters.data?.adapters.map((a) => <option key={a.adapter_id} value={a.adapter_id}>{a.adapter_id} {a.version}{a.aliases.length ? ` (alias ${a.aliases.join(", ")})` : ""}</option>)}
                </select>
              </Field>
              <Field label="Settings (JSON, no credentials)" hint="base_url must be an origin. scope.allowed_paths lists every path tests may call; anything else is refused.">
                <textarea className={`${inputClass} h-48 font-mono text-xs`} value={config} onChange={(e) => setConfig(e.target.value)} spellCheck={false} />
              </Field>
              <div>
                <p className="mb-1 text-xs font-medium text-muted">Test actor credentials (synthetic accounts only; sent once, stored encrypted)</p>
                {actorRows.map((row, i) => (
                  <div key={i} className="mb-2 flex gap-2">
                    <input aria-label="Actor name" className={`${inputClass} w-40`} value={row.name} placeholder="actor name"
                      onChange={(e) => setActorRows(actorRows.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)))} />
                    <input aria-label={`Credential for ${row.name || "actor"}`} type="password" autoComplete="off" className={inputClass} value={row.value}
                      placeholder="bearer token or API key" onChange={(e) => setActorRows(actorRows.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)))} />
                  </div>))}
                <Button onClick={() => setActorRows([...actorRows, { name: "", value: "" }])}>Add actor</Button>
              </div>
              <Button variant="primary" disabled={!!action.busy} onClick={submitConnection}>{action.busy === "connect" ? "Saving…" : "Save connection"}</Button>
            </div>)}
        </Card>
      </div>

      <Card className="p-5">
        <CardHeader title="Control profile" icon={<ScrollText className="size-4" aria-hidden />} count={profiles.data ? `${profiles.data.length} revisions` : undefined} />
        <p className="mt-1 text-sm text-muted">A profile selects which catalog controls this application is tested on and how. Controls without tests stay visible as not assessed. The person who proposes a revision cannot activate it.</p>
        <div className="mt-3 space-y-3">
          {profiles.data?.length === 0 && <EmptyState title="No profile yet" body="Generate a baseline from declared facts or paste a reviewed profile." />}
          {profiles.data?.map((p) => (
            <div key={p.revision} className="rounded-lg border border-line p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">r{p.revision} · {p.profile_id} {p.version}</span>
                <StatusBadge status={p.status === "active" ? "supported" : p.status === "rejected" ? "failed" : p.status === "proposed" ? "review_required" : "stale"} label={p.status} />
                <span className="text-xs text-muted">source {p.source} · proposed by {p.proposed_by}{p.reviewed_by ? ` · reviewed by ${p.reviewed_by}` : ""}</span>
              </div>
              {p.scope && <p className="mt-1 text-sm text-muted">{p.scope}</p>}
              <p className="mt-2 text-xs"><span className="font-medium">Assessed:</span> {p.assessed_controls.join(", ") || "none"} · <span className="font-medium">Not assessed:</span> {p.unassessed_controls.join(", ") || "none"} · {p.tests.length} tests</p>
              <details className="mt-2 text-xs"><summary className="cursor-pointer text-muted">Tests</summary>
                <ul className="mt-1 grid gap-1 md:grid-cols-2">{p.tests.map((t) => (
                  <li key={t.id} className="rounded bg-canvas px-2 py-1"><span className="font-mono">{t.id}</span> · {t.control} · {t.severity} · {t.template}{t.requires_review ? " · review" : ""}{t.mandatory ? " · mandatory" : ""}<br />{t.name}</li>))}</ul>
              </details>
              {p.status === "proposed" && canReview && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <input aria-label="Review note" className={`${inputClass} max-w-md`} placeholder="Review note (required)" value={notes[p.revision] ?? ""}
                    onChange={(e) => setNotes({ ...notes, [p.revision]: e.target.value })} />
                  <Button variant="primary" disabled={!!action.busy} onClick={() => action.run(`act-${p.revision}`, () => post(`${base}/profiles/${p.revision}/activate`, { note: notes[p.revision] ?? "" }), refreshAll)}>Activate</Button>
                  <Button variant="danger" disabled={!!action.busy} onClick={() => action.run(`rej-${p.revision}`, () => post(`${base}/profiles/${p.revision}/reject`, { note: notes[p.revision] ?? "" }), refreshAll)}>Reject</Button>
                </div>)}
            </div>))}
        </div>
        {canWrite && (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <Field label="Baseline from declared facts" hint="Uses only permitted catalogue templates. Anything you do not declare produces no test.">
                <textarea className={`${inputClass} h-48 font-mono text-xs`} value={hints} onChange={(e) => setHints(e.target.value)} spellCheck={false} />
              </Field>
              <Button className="mt-2" disabled={!!action.busy} onClick={proposeBaseline}>{action.busy === "baseline" ? "Generating…" : "Propose baseline profile"}</Button>
            </div>
            <div>
              <Field label="Reviewed profile (JSON)" hint="For example a profile prepared with your assessment analyst.">
                <textarea className={`${inputClass} h-48 font-mono text-xs`} value={profileJson} onChange={(e) => setProfileJson(e.target.value)} spellCheck={false} placeholder='{"profile_id": "...", "tests": [...]}' />
              </Field>
              <Button className="mt-2" disabled={!!action.busy || !profileJson.trim()} onClick={proposeProfile}>Propose profile revision</Button>
            </div>
          </div>)}
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="p-5">
          <CardHeader title="Runtime event sources" icon={<Radio className="size-4" aria-hidden />} />
          <p className="mt-1 text-sm text-muted">The AssureOps bridge runs next to your application, adds source identity, epoch and sequence, and delivers events durably.</p>
          <ul className="mt-3 space-y-2 text-sm">
            {sources.data?.map((s) => (
              <li key={s.source_id} className="flex items-center justify-between rounded-lg bg-canvas px-3 py-2">
                <span className="font-mono text-xs">{s.source_id} · {s.kind} · {s.environment}{s.revoked ? " · revoked" : ""}</span>
                {isOwner && !s.revoked && <Button variant="danger" onClick={() => action.run(`rev-${s.source_id}`, () => post(`${base}/event-sources/${s.source_id}/revoke`), refreshAll)}>Revoke</Button>}
              </li>))}
            {sources.data?.length === 0 && <li className="text-muted">No event source yet: runtime coverage stays not connected.</li>}
          </ul>
          {isOwner && (
            <div className="mt-3 flex gap-2">
              <input aria-label="Source ID" className={inputClass} value={sourceId} onChange={(e) => setSourceId(e.target.value)} />
              <Button onClick={() => action.run("source", async () => {
                const r = await post<{ token: string }>(`${base}/event-sources`, { source_id: sourceId, kind: "application" });
                setIssuedToken(r.token);
              }, refreshAll)}>Issue credential</Button>
            </div>)}
          {issuedToken && <Notice tone="warn"><p className="font-medium">Copy this source token into the bridge&apos;s secret store now. It is not shown again.</p>
            <code className="mt-1 block break-all font-mono text-xs">{issuedToken}</code>
            <button type="button" className="mt-2 text-xs underline" onClick={() => setIssuedToken(null)}>I stored it, hide</button></Notice>}
        </Card>

        <Card className="p-5">
          <CardHeader title="Permitted test catalogue" icon={<ShieldCheck className="size-4" aria-hidden />} />
          <p className="mt-1 text-sm text-muted">Tests are data: these templates with typed arguments. No profile or model output can add code.</p>
          <ul className="mt-3 space-y-1 text-sm">{adapters.data?.templates.map((t) => (
            <li key={t.id}><span className="font-mono text-xs">{t.id}</span> — {t.title}{t.description ? <span className="text-muted"> · {t.description}</span> : null}</li>))}</ul>
        </Card>
      </div>
      <p className="text-xs text-muted">Reload is safe at any point: every value here comes from the API. <button type="button" className="underline" onClick={async () => { await api(`${base}/connection`).catch(() => null); refreshAll(); }}>Refresh now</button></p>
    </div>
  );
}
