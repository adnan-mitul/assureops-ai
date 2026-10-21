"use client";

import { api, useAction, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, ErrorBanner, LoadingState, Mono, StatusBadge, TableWrap, Td, Th, inputClass } from "@assureops/ui/components";
import { useState } from "react";
import { money } from "@assureops/ui/format";
import { Bot, Boxes, Database, ScrollText } from "lucide-react";
import { Fact, PageTop } from "@/components/bits";
import { MembersPanel } from "@/components/MembersPanel";
import type { Settings } from "@/lib/types";

function show(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function KeyValues({ data, format }: { data: Record<string, unknown>; format?: (key: string, value: unknown) => string }) {
  return (
    <dl className="grid gap-3 sm:grid-cols-2">
      {Object.entries(data).map(([k, v]) => <Fact key={k} label={k.replaceAll("_", " ")}>{format?.(k, v) ?? show(v)}</Fact>)}
    </dl>
  );
}

export default function SettingsPage() {
  const { data, error, loading, refresh } = usePoll<Settings>("/v1/settings", 0);

  if (loading && !data) return <LoadingState label="Loading settings…" />;
  if (!data) return <ApiErrorBanner error={error} />;

  const p = data.profile;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Settings" title="Workspace settings" subtitle={<>Workspace <span className="font-mono">{data.workspace}</span> · your role: <strong className="capitalize">{data.your_role}</strong></>} />
      <ApiErrorBanner error={error} />

      <div className="grid gap-5 xl:grid-cols-2">
        <MembersPanel members={data.members} isOwner={data.your_role === "owner"} you={data.you} onChanged={refresh} />

        <Card>
          <CardHeader title="Data policy and retention" icon={<Database className="size-4" aria-hidden />} />
          <div className="space-y-4 px-5 pb-5">
            <dl className="grid gap-3 sm:grid-cols-3">
              <Fact label="Inference">{data.data_policy.inference.replaceAll("_", " ")}</Fact>
              <Fact label="External processing">{data.data_policy.external_processing ? "Allowed for approved phases" : "Not allowed (private only)"}</Fact>
              <Fact label="Training on your evidence">{data.data_policy.training_on_customer_evidence ? "Yes" : "Never"}</Fact>
              <Fact label="Evidence retention">{data.retention.evidence_days} days</Fact>
              <Fact label="Runtime event retention">{data.retention.runtime_events_days} days</Fact>
            </dl>
          </div>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader title="Applications" icon={<Boxes className="size-4" aria-hidden />} count={`${data.applications.length}`} />
        <TableWrap minWidth="min-w-[860px]">
          <thead><tr><Th>Application</Th><Th>Environment</Th><Th>Mode</Th><Th>Target</Th><Th>Authorized scope</Th></tr></thead>
          <tbody className="divide-y divide-line">
            {data.applications.map((a) => (
              <tr key={a.id}>
                <Td><p className="font-medium">{a.name}</p><Mono>{a.id}</Mono></Td>
                <Td className="capitalize">{a.environment}</Td>
                <Td>{a.mode.replaceAll("_", " ")}</Td>
                <Td className="text-xs break-all"><p>{a.target_url}</p><p className="text-muted">tools {a.tools_url}</p></Td>
                <Td className="text-xs">
                  <ul className="space-y-0.5">{Object.entries(a.authorized_scope).map(([k, v]) => <li key={k}><span className="text-muted">{k.replaceAll("_", " ")}:</span> {show(v)}</li>)}</ul>
                </Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      </Card>

      <Card className="mt-5">
        <CardHeader title={`Assessment profile ${p.version}`} icon={<ScrollText className="size-4" aria-hidden />} count={`${Object.keys(p.controls).length} controls`} />
        <p className="-mt-1 px-5 pb-3 text-xs text-muted">Control IDs are AssureOps internal identifiers, not clauses of an official standard. Readiness under this profile is not a certification.</p>
        <div className="grid gap-5 px-5 pb-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div className="overflow-hidden rounded-lg border border-line">
            <TableWrap minWidth="min-w-[420px]">
              <thead><tr><Th>Control</Th><Th>Family</Th><Th>Weight</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {Object.entries(p.controls).map(([id, c]) => <tr key={id}><Td className="whitespace-nowrap">{id} {c.name}</Td><Td className="text-muted">{c.family}</Td><Td>{c.weight}</Td></tr>)}
              </tbody>
            </TableWrap>
          </div>
          <div className="space-y-5">
            <section>
              <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">Gate policy</h3>
              <KeyValues data={p.gate_policy} />
            </section>
            <section>
              <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">Requirements</h3>
              <KeyValues data={p.requirements} format={(k, v) => (k.endsWith("_minor") && typeof v === "number" ? `${v} minor units (${money(v)})` : show(v))} />
            </section>
            <section>
              <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">Evidence freshness</h3>
              <p className="text-sm">Evidence older than {p.evidence_freshness_days} days becomes stale and must be retested.</p>
            </section>
          </div>
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="Model routes" icon={<Bot className="size-4" aria-hidden />} count={`${data.model_routes.filter((m) => m.enabled).length} enabled`} />
        <TableWrap minWidth="min-w-[720px]">
          <thead><tr><Th>Phase</Th><Th>Candidate model</Th><Th>Route</Th><Th>Status</Th></tr></thead>
          <tbody className="divide-y divide-line">
            {data.model_routes.map((m) => (
              <tr key={m.phase}>
                <Td className="capitalize">{m.id ? `${m.id} · ` : ""}{m.phase.replaceAll("_", " ")}{m.optional && <span className="ml-1 text-xs text-muted">(optional)</span>}</Td>
                <Td><Mono>{m.model}</Mono>{m.parameters && <span className="ml-1 text-xs text-muted">{m.parameters}</span>}</Td>
                <Td className="text-xs">{m.route?.provider ? `${m.route.provider}${m.route.model ? ` · ${m.route.model}` : ""}${m.route.external ? " (external)" : ""}` : "none configured"}</Td>
                <Td>{m.enabled ? <StatusBadge status="accepted" label="Enabled" /> : <span title={m.status}><StatusBadge status="unverified" label={(m.status ?? "disabled").split(":")[0].replaceAll("_", " ")} /></span>}</Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
        <p className="px-5 py-3 text-xs text-muted">Models only propose (requirements, links, tests, explanations); deterministic rules and reviewers decide every result. A phase stays disabled until its exact model is qualified, and an external provider receives nothing unless this workspace allows external processing.</p>
        {data.your_role === "owner" && <DataPolicy current={data.data_policy.external_processing} />}
      </Card>
    </div>
  );
}


function DataPolicy({ current }: { current: boolean }) {
  const action = useAction();
  const [reason, setReason] = useState("");
  const [value, setValue] = useState(current);
  return (
    <div className="border-t border-line px-5 py-4">
      <p className="text-sm font-medium">External processing</p>
      <p className="text-xs text-muted">When allowed, only phases approved for an external provider (today: explanation drafts) may send minimized, redacted facts to it. A private-server outage never enables it.</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={value} onChange={(e) => setValue(e.target.checked)} /> Allow external processing</label>
        <input aria-label="Reason" className={`${inputClass} max-w-sm`} placeholder="Reason (recorded in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <Button disabled={!!action.busy || reason.trim().length < 5 || value === current}
          onClick={() => action.run("policy", () => api("/v1/workspace/data-policy", { method: "PUT", body: JSON.stringify({ external_processing: value, reason }) }),
            () => window.location.reload())}>Save policy</Button>
      </div>
      {action.error && <ErrorBanner message={action.error} />}
    </div>
  );
}
