"use client";

import { post, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, EmptyState, ErrorBanner, Field, LoadingState, Notice, StatusBadge, inputClass } from "@assureops/ui/components";
import { Bot, FileSearch, FileUp, GitBranch, Library, ScanSearch } from "lucide-react";
import { useState } from "react";
import { PageTop, useRouteId, WithSuspense } from "@/components/bits";
import { useApp } from "@/lib/app-context";

type Phase = { id: string; phase: string; model: string; parameters: string; enabled: boolean; status: string; route: { provider: string | null; model: string | null; external: boolean } };
type Result = { id: string; phase: string; phase_name: string; status: string; output: Record<string, unknown>; supporting_spans: { source_id: string; quote: string }[];
  unknowns: string[]; versions: Record<string, string>; error: string | null; reviewer: string | null; requested_by: string; created_at: number };
type Source = { id: string; title: string; kind: string; chars: number; approved_by: string };
type Analysis = { id: string; release_id: string; status: string; analyzer: string | null; summary: Record<string, unknown>; error: string | null; created_at: number };
type Release = { id: string; version: string };
type Report = { report_id: string; release: string; state: string };
type Run = { id: string; test_id: string; release: string; outcome: string };
type Monitoring = { incidents: { id: string; control: string; state: string; title: string }[] };
type PlanResult = { revision: number; plan: { tests: number; controls_tested: string[]; controls_not_assessed: string[]; requirements: number;
  skipped: { result: string; name: string | null; reason: string }[]; needs_facts: { name: string | null; template: string; missing: string[] }[] } };

const PHASE_HELP: Record<string, string> = {
  A: "Extract requirements with quoted spans from approved sources.",
  B: "Propose test-to-component dependency links for the latest release.",
  C: "Propose catalogue tests from accepted requirements; accepted proposals build the application's test plan.",
  D: "Score a recorded test run's responses against atomic claims (advisory).",
  E: "Summarize an incident with cited events and retest suggestions.",
  F: "Draft a plain-language explanation of a published report.",
  G: "Screen untrusted text for injection attempts (advisory).",
};

export default function AiPage() {
  return <WithSuspense label="Loading AI phases…"><AiView /></WithSuspense>;
}

function AiView() {
  const appId = useRouteId();
  const base = `/v1/applications/${encodeURIComponent(appId)}`;
  const { canWrite, canReview, me } = useApp();
  const isOwner = me?.role === "owner";
  const phases = usePoll<{ external_processing: boolean; phases: Phase[] }>("/v1/ai/phases", 30000);
  const results = usePoll<Result[]>(`${base}/ai/results`, 5000);
  const sources = usePoll<Source[]>(`${base}/sources`, 0);
  const releases = usePoll<Release[]>(`${base}/releases`, 0);
  const reports = usePoll<Report[]>(`/v1/reports?application_id=${encodeURIComponent(appId)}`, 0);
  const runs = usePoll<Run[]>(`/v1/evidence?application_id=${encodeURIComponent(appId)}`, 0);
  const monitoring = usePoll<Monitoring>(`/v1/monitoring?application_id=${encodeURIComponent(appId)}`, 0);
  const analyses = usePoll<Analysis[]>(`${base}/source-analyses`, 5000);
  const action = useAction();
  const [form, setForm] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [source, setSource] = useState({ title: "", kind: "policy", text: "" });
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<{ method: string; results: { score: number; title: string; text: string }[] } | null>(null);
  const [codeMap, setCodeMap] = useState('{"code:target": "app.py", "code:transport": "server.py"}');
  const [ciToken, setCiToken] = useState<string | null>(null);
  const [repo, setRepo] = useState("");
  const [bound, setBound] = useState<string | null>(null);
  // Accepts owner/name or a pasted link such as https://github.com/owner/name(.git)
  const repoName = repo.trim().replace(/^https?:\/\/(www\.)?github\.com\//i, "").replace(/\.git$/i, "").replace(/\/+$/, "");
  const repoValid = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repoName);
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [facts, setFacts] = useState("{}");
  const factsValid = (() => { try { const v = JSON.parse(facts); return typeof v === "object" && v !== null && !Array.isArray(v); } catch { return false; } })();
  const acceptedA = results.data?.filter((r) => r.phase === "A" && r.status === "accepted").length ?? 0;
  const acceptedC = results.data?.filter((r) => r.phase === "C" && r.status === "accepted").length ?? 0;

  const request = (phase: string) => {
    const refs: Record<string, unknown> = {};
    if (phase === "B") refs.release_id = releases.data?.[0]?.id;
    if (phase === "D") { refs.run_id = form.run_id; if (form.claims) refs.claims = form.claims.split("\n").filter(Boolean); }
    if (phase === "E") refs.incident_id = form.incident_id;
    if (phase === "F") refs.report_id = form.report_id;
    if (phase === "G") { if (form.texts) refs.texts = form.texts.split("\n").filter(Boolean); else refs.source_ids = sources.data?.map((s) => s.id); }
    if (phase === "A" && form.query) refs.query = form.query;
    action.run(`req-${phase}`, () => post(`${base}/ai/${phase}`, refs), results.refresh);
  };

  const upload = async (file: File) => {
    const buffer = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let i = 0; i < buffer.length; i += 0x8000) binary += String.fromCharCode(...buffer.subarray(i, i + 0x8000));
    const release = releases.data?.[0];
    if (!release) return;
    action.run("snapshot", () => post(`${base}/releases/${release.id}/source-analyses`, { zip_base64: btoa(binary), code_map: JSON.parse(codeMap) }), analyses.refresh);
  };

  if (phases.loading && !phases.data) return <LoadingState label="Loading AI phases…" />;

  return (
    <div className="mx-auto max-w-[1400px] space-y-5">
      <PageTop eyebrow="Applications · AI and analysis" title={`AI phases and source analysis for ${appId}`}
        subtitle="Models only propose. Every output is validated against its sources and schema, and a different person accepts or rejects it. Rules and reviewers decide results." />
      <ApiErrorBanner error={phases.error} />
      {action.error && <ErrorBanner message={action.error} />}

      <Card className="p-5">
        <CardHeader title="Phase routes" icon={<Bot className="size-4" aria-hidden />} count={`${phases.data?.phases.filter((p) => p.enabled).length ?? 0} enabled`} />
        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {phases.data?.phases.map((p) => (
            <div key={p.id} className="rounded-lg border border-line p-3 text-sm">
              <div className="flex items-center justify-between"><span className="font-semibold">{p.id} · {p.phase.replaceAll("_", " ")}</span>
                <StatusBadge status={p.enabled ? "supported" : "unverified"} label={p.enabled ? "enabled" : "disabled"} /></div>
              <p className="mt-1 font-mono text-[11px] text-muted">{p.route.provider ?? "no route"} · {p.route.model ?? p.model}</p>
              <p className="mt-1 text-xs text-muted">{p.enabled ? PHASE_HELP[p.id] ?? "Used automatically by retrieval." : p.status}</p>
            </div>))}
        </div>
      </Card>

      {canWrite || canReview ? (
        <Card className="p-5">
          <CardHeader title="Request a phase" icon={<ScanSearch className="size-4" aria-hidden />} />
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <Field label="A · focus query (optional)"><input className={inputClass} value={form.query ?? ""} onChange={(e) => setForm({ ...form, query: e.target.value })} /></Field>
              <div className="flex flex-wrap gap-2">
                {["A", "B", "C"].map((ph) => <Button key={ph} disabled={!!action.busy} onClick={() => request(ph)}>Run {ph}</Button>)}
              </div>
              <Field label="D · recorded run"><select className={inputClass} value={form.run_id ?? ""} onChange={(e) => setForm({ ...form, run_id: e.target.value })}>
                <option value="">choose a run</option>{runs.data?.slice(0, 40).map((r) => <option key={r.id} value={r.id}>{r.test_id} · {r.release} · {r.outcome}</option>)}</select></Field>
              <Field label="D · atomic claims (one per line, optional)"><textarea className={`${inputClass} h-16`} value={form.claims ?? ""} onChange={(e) => setForm({ ...form, claims: e.target.value })} /></Field>
              <Button disabled={!!action.busy || !form.run_id} onClick={() => request("D")}>Run D</Button>
            </div>
            <div className="space-y-2">
              <Field label="E · incident"><select className={inputClass} value={form.incident_id ?? ""} onChange={(e) => setForm({ ...form, incident_id: e.target.value })}>
                <option value="">choose an incident</option>{monitoring.data?.incidents.map((i) => <option key={i.id} value={i.id}>{i.control} · {i.state} · {i.title}</option>)}</select></Field>
              <Button disabled={!!action.busy || !form.incident_id} onClick={() => request("E")}>Run E</Button>
              <Field label="F · published report"><select className={inputClass} value={form.report_id ?? ""} onChange={(e) => setForm({ ...form, report_id: e.target.value })}>
                <option value="">choose a report</option>{reports.data?.map((r) => <option key={r.report_id} value={r.report_id}>{r.release} · {r.state}</option>)}</select></Field>
              <Button disabled={!!action.busy || !form.report_id} onClick={() => request("F")}>Run F</Button>
              <Field label="G · untrusted texts (one per line; empty = approved sources)"><textarea className={`${inputClass} h-16`} value={form.texts ?? ""} onChange={(e) => setForm({ ...form, texts: e.target.value })} /></Field>
              <Button disabled={!!action.busy} onClick={() => request("G")}>Run G</Button>
            </div>
          </div>
        </Card>) : null}

      <Card className="p-5">
        <CardHeader title="Results" icon={<FileSearch className="size-4" aria-hidden />} count={`${results.data?.length ?? 0}`} />
        {results.data?.length === 0 && <EmptyState title="No phase results yet" body="Request a phase above." />}
        <div className="mt-3 space-y-3">
          {results.data?.map((r) => (
            <div key={r.id} className="rounded-lg border border-line p-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{r.phase} · {r.phase_name.replaceAll("_", " ")}</span>
                <StatusBadge status={r.status === "accepted" ? "supported" : r.status === "rejected" || r.status === "unavailable" ? "failed" : r.status === "proposed" ? "proposed" : "review_required"} label={r.status} />
                <span className="font-mono text-[11px] text-muted">{r.versions.provider ?? "-"} · {r.versions.model ?? "-"} · prompt {r.versions.prompt}</span>
                <span className="text-xs text-muted">by {r.requested_by}{r.reviewer ? ` · reviewed by ${r.reviewer}` : ""}</span>
              </div>
              {r.error && <p className="mt-1 text-xs text-red-700">{r.error}</p>}
              {r.output && Object.keys(r.output).length > 0 && (
                <details className="mt-2"><summary className="cursor-pointer text-xs text-muted">Output</summary>
                  <pre className="mt-1 max-h-72 overflow-auto rounded bg-canvas p-2 text-[11px]">{JSON.stringify(r.output, null, 2)}</pre></details>)}
              {r.supporting_spans?.length > 0 && <p className="mt-1 text-xs text-muted">{r.supporting_spans.length} quoted source spans verified</p>}
              {["proposed", "review_required"].includes(r.status) && canReview && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <input aria-label="Review note" className={`${inputClass} max-w-sm`} placeholder="Review note" value={notes[r.id] ?? ""} onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })} />
                  <Button variant="primary" disabled={!!action.busy} onClick={() => action.run(`a-${r.id}`, () => post(`/v1/ai/results/${r.id}/review`, { decision: "accept", note: notes[r.id] ?? "" }), results.refresh)}>Accept</Button>
                  <Button variant="danger" disabled={!!action.busy} onClick={() => action.run(`r-${r.id}`, () => post(`/v1/ai/results/${r.id}/review`, { decision: "reject", note: notes[r.id] ?? "" }), results.refresh)}>Reject</Button>
                </div>)}
            </div>))}
        </div>
      </Card>

      {canWrite && (
        <Card className="p-5">
          <CardHeader title="Build the test plan" icon={<ScanSearch className="size-4" aria-hidden />}
            count={`${acceptedA} requirement result${acceptedA === 1 ? "" : "s"} · ${acceptedC} test result${acceptedC === 1 ? "" : "s"} accepted`} />
          <p className="mt-2 text-sm text-muted">
            Assembles one proposed profile revision from the accepted phase A requirements and phase C tests, plus the release identity check.
            Controls without an accepted test stay visible as not assessed. A different person reviews and activates it on the Connect page.
          </p>
          <Field label="Declared application facts (JSON; filled into tests that need them)">
            <textarea className={`${inputClass} h-20 font-mono text-xs`} value={facts} onChange={(e) => setFacts(e.target.value)}
              placeholder={'{"reply_path": "reply", "markers": ["INV-"], "expect_contains": ["14 days"], "canaries": ["sk-test-..."]}'} />
          </Field>
          <p className="mt-1 text-xs text-muted">Facts a model cannot know: markers, expect_contains, reply_path, abstention_patterns, canaries, ledger, match, list_path.</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button variant="primary" disabled={!!action.busy || acceptedC === 0 || !factsValid}
              onClick={() => action.run("plan", async () => setPlan(await post<PlanResult>(`${base}/profiles/ai-plan`, { facts: JSON.parse(facts) })))}>Build test plan</Button>
            {acceptedC === 0 && <span className="text-xs text-muted">Run C and have a reviewer accept its proposal first.</span>}
          </div>
          {plan && (
            <div className="mt-3"><Notice tone="success">
              Revision {plan.revision} proposed with {plan.plan.tests} tests covering {plan.plan.controls_tested.join(", ")}.
              Not assessed: {plan.plan.controls_not_assessed.join(", ") || "none"}.
              {plan.plan.skipped.length > 0 && ` ${plan.plan.skipped.length} proposed test(s) no longer match the catalogue and were left out.`}
              {plan.plan.needs_facts.length > 0 && ` ${plan.plan.needs_facts.length} test(s) wait for facts: ${Array.from(new Set(plan.plan.needs_facts.flatMap((n) => n.missing))).join(", ")}.`}{" "}
              <a className="underline" href={`/applications/${encodeURIComponent(appId)}/connect`}>Review and activate</a>
            </Notice></div>)}
        </Card>)}

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="p-5">
          <CardHeader title="Approved reference sources" icon={<Library className="size-4" aria-hidden />} count={`${sources.data?.length ?? 0}`} />
          <ul className="mt-2 space-y-1 text-sm">{sources.data?.map((s) => <li key={s.id}>{s.title} <span className="text-xs text-muted">({s.kind}, {s.chars} chars, approved by {s.approved_by})</span></li>)}</ul>
          {canReview && (
            <div className="mt-3 space-y-2">
              <input aria-label="Title" className={inputClass} placeholder="Title" value={source.title} onChange={(e) => setSource({ ...source, title: e.target.value })} />
              <textarea aria-label="Source text" className={`${inputClass} h-24`} placeholder="Policy, requirement or design text" value={source.text} onChange={(e) => setSource({ ...source, text: e.target.value })} />
              <Button disabled={!!action.busy || source.text.length < 20} onClick={() => action.run("src", () => post(`${base}/sources`, source), () => { setSource({ title: "", kind: "policy", text: "" }); sources.refresh(); })}>Approve source</Button>
            </div>)}
          <div className="mt-3 flex gap-2"><input aria-label="Search" className={inputClass} placeholder="Search sources" value={query} onChange={(e) => setQuery(e.target.value)} />
            <Button onClick={() => action.run("search", async () => setSearch(await post(`${base}/sources/search`, { query, k: 3 })))}>Search</Button></div>
          {search && <div className="mt-2 text-xs"><p className="text-muted">method: {search.method}</p>{search.results.map((r, i) => <p key={i} className="mt-1"><b>{r.title}</b> ({r.score}) {r.text.slice(0, 160)}</p>)}</div>}
        </Card>

        <Card className="p-5">
          <CardHeader title="Source / build analysis (REA + built-in collector)" icon={<FileUp className="size-4" aria-hidden />} />
          <p className="mt-1 text-sm text-muted">Upload an authorized source snapshot (.zip) for release {releases.data?.[0]?.version ?? "—"}. It is stored privately and never executed; unknown components broaden retesting.</p>
          {canWrite && (
            <div className="mt-2 space-y-2">
              <Field label="Manifest component → snapshot path"><input className={`${inputClass} font-mono text-xs`} value={codeMap} onChange={(e) => setCodeMap(e.target.value)} /></Field>
              <input aria-label="Snapshot zip" type="file" accept=".zip" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </div>)}
          <ul className="mt-3 space-y-2 text-xs">{analyses.data?.map((a) => (
            <li key={a.id} className="rounded bg-canvas p-2"><b>{a.status}</b> · {a.analyzer ?? "pending"}{a.error ? ` · ${a.error}` : ""}
              <details><summary className="cursor-pointer text-muted">summary</summary><pre className="max-h-60 overflow-auto">{JSON.stringify(a.summary, null, 2)}</pre></details></li>))}</ul>
        </Card>
      </div>

      {isOwner && (
        <div id="repository" className="scroll-mt-24"><Card className="p-5">
          <CardHeader title="Release gate and repository" icon={<GitBranch className="size-4" aria-hidden />} />
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <Button onClick={() => action.run("ci", async () => setCiToken((await post<{ token: string }>(`${base}/ci-credentials`, {})).token))}>Issue CI credential</Button>
            <Field label="Bind GitHub repository (owner/name or its GitHub link)">
              <input className={inputClass} value={repo} placeholder="acme/refund-bot or https://github.com/acme/refund-bot"
                onChange={(e) => { setRepo(e.target.value); setBound(null); }} /></Field>
            <Button disabled={!!action.busy || !repoValid} onClick={() => action.run("repo", async () => {
              const res = await post<{ repository: string }>(`${base}/repositories`, { repository: repoName });
              setBound(res.repository); setRepo("");
            })}>Bind</Button>
          </div>
          {repo && !repoValid && <p className="mt-1 text-xs text-red-700">Enter owner/name, for example acme/refund-bot, or paste the repository&apos;s GitHub link.</p>}
          {bound && <div className="mt-3"><Notice tone="success">Repository {bound} is bound to this application. Its pipeline can now ask for release decisions with a CI credential.</Notice></div>}
          {ciToken && <Notice tone="warn"><p className="font-medium">Store this as a CI secret now; it is not shown again.</p><code className="break-all text-xs">{ciToken}</code></Notice>}
          <p className="mt-2 text-xs text-muted">Pipelines call /v1/integration/release-gate/check with the exact commit SHA and re-verify the receipt at deploy time (see docs/integrations/customer-release-gate.yml).</p>
        </Card></div>)}
    </div>
  );
}
