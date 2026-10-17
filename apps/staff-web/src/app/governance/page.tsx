"use client";

import { usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Card, CardHeader, LoadingState, Mono, Notice, PageHeader, SeverityBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { BookCheck, Bot, KeyRound, Scale, Users } from "lucide-react";
import { ROLE_LABEL } from "@/lib/staff-context";
import type { Governance } from "@/lib/types";

function requirementValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export default function GovernancePage() {
  const { data, error, loading } = usePoll<Governance>("/v1/staff/governance", 0);

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Governance" subtitle="The control profile, gate policy, test catalog, model routes and staff permissions in force." />
      <ApiErrorBanner error={error} />
      {loading && !data ? <LoadingState label="Loading governance…" /> : !data ? null : (
        <div className="space-y-5">
          <Card className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-xs text-muted">Control profile</p>
                <p className="text-lg font-bold">{data.profile.version}</p>
                <p className="text-xs text-muted">Digest <Mono>{data.profile.digest}</Mono></p>
              </div>
              <p className="max-w-xl text-xs text-muted">Control IDs are AssureOps internal identifiers, not clauses of an official standard. Readiness within this profile is not a certification.</p>
            </div>
          </Card>

          <div className="grid gap-5 xl:grid-cols-2">
            <Card className="min-w-0">
              <CardHeader title="Controls" icon={<BookCheck className="size-4" aria-hidden />} count={`${Object.keys(data.profile.controls).length}`} />
              <TableWrap minWidth="min-w-[480px]">
                <thead><tr><Th>Control</Th><Th>Family</Th><Th>Weight</Th></tr></thead>
                <tbody className="divide-y divide-line">
                  {Object.entries(data.profile.controls).map(([cid, c]) => (
                    <tr key={cid}><Td><span className="font-medium">{cid}</span> {c.name}</Td><Td className="text-muted">{c.family}</Td><Td>{c.weight}</Td></tr>
                  ))}
                </tbody>
              </TableWrap>
            </Card>

            <div className="min-w-0 space-y-5">
              <Card className="p-5">
                <h2 className="flex items-center gap-2 text-[15px] font-semibold"><Scale className="size-4" aria-hidden />Gate policy {data.profile.gate_policy.version}</h2>
                <dl className="mt-3 space-y-2 text-sm">
                  <div><dt className="text-xs text-muted">Blocking failure severities</dt>
                    <dd className="mt-1 flex flex-wrap gap-1">{data.profile.gate_policy.blocking_severities.map((s) => <SeverityBadge key={s} severity={s} />)}</dd></div>
                  <div><dt className="text-xs text-muted">Incomplete when evidence is</dt>
                    <dd className="mt-0.5">{data.profile.gate_policy.incomplete_when.map((s) => s.replaceAll("_", " ")).join(", ")}</dd></div>
                </dl>
              </Card>
              <Card className="p-5">
                <h2 className="text-[15px] font-semibold">Requirements</h2>
                <dl className="mt-3 space-y-1.5 text-sm">
                  {Object.entries(data.profile.requirements).map(([k, v]) => (
                    <div key={k} className="flex flex-wrap justify-between gap-2"><dt className="text-muted">{k.replaceAll("_", " ")}</dt><dd className="font-medium">{requirementValue(v)}</dd></div>
                  ))}
                </dl>
              </Card>
              <Card className="p-5">
                <h2 className="flex items-center gap-2 text-[15px] font-semibold"><KeyRound className="size-4" aria-hidden />Identity</h2>
                <p className="mt-2 text-sm">Provider: {data.identity.provider}</p>
                <div className="mt-2"><Notice tone="warn">Staff MFA: {data.identity.staff_mfa}</Notice></div>
              </Card>
            </div>
          </div>

          <Card>
            <CardHeader title="Test catalog" count={`${data.profile.tests.length} tests`} />
            <TableWrap minWidth="min-w-[720px]">
              <thead><tr><Th>Test</Th><Th>Control</Th><Th>Severity</Th><Th>Trials</Th><Th>Flags</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.profile.tests.map((t) => (
                  <tr key={t.id}>
                    <Td><p>{t.name}</p><Mono>{t.id}</Mono></Td>
                    <Td>{t.control}</Td>
                    <Td><SeverityBadge severity={t.severity} /></Td>
                    <Td>{t.trials}</Td>
                    <Td className="text-xs text-muted">{[t.requires_review && "Human review required", t.mandatory && "Mandatory boundary check"].filter(Boolean).join(" · ") || "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          </Card>

          <Card>
            <CardHeader title="Model routes" icon={<Bot className="size-4" aria-hidden />} count={`${data.model_routes.filter((m) => m.enabled).length} enabled · ${data.qualification_records.length} qualification records`} />
            <div className="px-5 pb-3">
              <Notice>{data.qualification_records.length === 0 ? "No model route has a qualification record, so none is enabled. Semantic steps go to human review." : `${data.qualification_records.length} qualification records on file.`}</Notice>
            </div>
            <TableWrap minWidth="min-w-[640px]">
              <thead><tr><Th>Phase</Th><Th>Candidate model</Th><Th>Route state</Th><Th>Qualification</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.model_routes.map((m) => (
                  <tr key={m.phase}>
                    <Td className="capitalize">{m.phase.replaceAll("_", " ")}{m.optional && <span className="ml-1 text-xs text-muted">(optional)</span>}</Td>
                    <Td><Mono>{m.model}</Mono></Td>
                    <Td>{m.enabled ? <span className="text-xs font-semibold text-emerald-700">Enabled</span> : <span className="text-xs text-muted">Disabled</span>}</Td>
                    <Td className="text-xs text-muted">{m.qualification ? JSON.stringify(m.qualification) : "None"}</Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          </Card>

          <Card>
            <CardHeader title="Staff permissions" icon={<Users className="size-4" aria-hidden />} count={`${data.staff_permissions.length} staff`} />
            <TableWrap minWidth="min-w-[560px]">
              <thead><tr><Th>User</Th><Th>Name</Th><Th>Active roles</Th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.staff_permissions.map((s) => (
                  <tr key={s.user}>
                    <Td>{s.user}</Td>
                    <Td>{s.name}</Td>
                    <Td>{s.roles.length ? s.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ") : <span className="text-muted">None</span>}</Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
            <p className="border-t border-line px-5 py-3 text-xs text-muted">Roles grant duties, not data: customer content is reachable only through an active case assignment.</p>
          </Card>
        </div>
      )}
    </div>
  );
}
