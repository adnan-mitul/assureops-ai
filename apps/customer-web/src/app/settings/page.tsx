"use client";

import { usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Card, CardHeader, LoadingState, Mono, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { money } from "@assureops/ui/format";
import { Bot, Boxes, Database, ScrollText, Users } from "lucide-react";
import { Fact, PageTop } from "@/components/bits";
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
  const { data, error, loading } = usePoll<Settings>("/v1/settings", 0);

  if (loading && !data) return <LoadingState label="Loading settings…" />;
  if (!data) return <ApiErrorBanner error={error} />;

  const p = data.profile;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageTop eyebrow="Settings" title="Workspace settings" subtitle={<>Workspace <span className="font-mono">{data.workspace}</span> · your role: <strong className="capitalize">{data.your_role}</strong> · read-only</>} />
      <ApiErrorBanner error={error} />

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="Members" icon={<Users className="size-4" aria-hidden />} count={`${data.members.length}`} />
          <TableWrap minWidth="min-w-[400px]">
            <thead><tr><Th>Name</Th><Th>User</Th><Th>Role</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {data.members.map((m) => <tr key={m.user}><Td>{m.name}</Td><Td><Mono>{m.user}</Mono></Td><Td className="capitalize">{m.role}</Td></tr>)}
            </tbody>
          </TableWrap>
          <p className="px-5 py-3 text-xs text-muted">Owners and developers submit releases and start assessments; owners and reviewers grant approvals; viewers read only.</p>
        </Card>

        <Card>
          <CardHeader title="Data policy and retention" icon={<Database className="size-4" aria-hidden />} />
          <div className="space-y-4 px-5 pb-5">
            <dl className="grid gap-3 sm:grid-cols-3">
              <Fact label="Inference">{data.data_policy.inference.replaceAll("_", " ")}</Fact>
              <Fact label="External model fallback">{data.data_policy.external_fallback ? "Allowed" : "Not allowed"}</Fact>
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
        <TableWrap minWidth="min-w-[560px]">
          <thead><tr><Th>Phase</Th><Th>Model</Th><Th>Status</Th></tr></thead>
          <tbody className="divide-y divide-line">
            {data.model_routes.map((m) => (
              <tr key={m.phase}>
                <Td className="capitalize">{m.phase.replaceAll("_", " ")}{m.optional && <span className="ml-1 text-xs text-muted">(optional)</span>}</Td>
                <Td><Mono>{m.model}</Mono></Td>
                <Td>{m.enabled ? <StatusBadge status="accepted" label="Enabled" /> : <StatusBadge status="unverified" label={m.qualification ? "Disabled" : "Disabled · not qualified"} />}</Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
        <p className="px-5 py-3 text-xs text-muted">No model contributes to results until it passes qualification. All current results come from deterministic tests and rules.</p>
      </Card>
    </div>
  );
}
