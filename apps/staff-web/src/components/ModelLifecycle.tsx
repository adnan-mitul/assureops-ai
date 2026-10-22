"use client";

import { post, usePoll } from "@assureops/ui/client";
import { ApiErrorBanner, Button, Card, CardHeader, Field, Mono, StatusBadge, TableWrap, Td, Th, inputClass } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { GitCommitVertical } from "lucide-react";
import { useState } from "react";
import { ActionDone, ActionError } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import { useStaff } from "@/lib/staff-context";

type RouteRow = {
  id: string; phase: string; provider: string; model: string; stage: string; canary_percent: number;
  shadow: { runs: number; valid: number }; canary: { runs: number; valid: number; invalid: number }; changed_by: string; changed_at: number;
  history: { from: string | null; to: string; actor: string; note: string; at: number }[];
};
type Listing = { routes: RouteRow[]; serving: { phase: string; name: string; provider: string | null; model: string | null; enabled: boolean; status: string }[];
  rules: { shadow_min_runs: number; canary_min_runs: number; min_valid_rate: number } };

const NEXT: Record<string, string[]> = { development: ["holdout"], holdout: ["shadow", "canary"], shadow: ["canary"], canary: ["active"],
  retired: ["development"], rolled_back: ["development"] };
const BADGE: Record<string, string> = { development: "draft", holdout: "queued", shadow: "running", canary: "running", active: "accepted",
  retired: "superseded", rolled_back: "withdrawn" };

/** Candidate models move development -> holdout -> shadow -> canary -> active; the backend enforces every gate. */
export function ModelLifecycle() {
  const { hasRole } = useStaff();
  const canChange = hasRole("operator", "admin");
  const data = usePoll<Listing>("/v1/staff/admin/model-routes", 15000);
  const action = useStaffAction(() => data.refresh());
  const [form, setForm] = useState({ phase: "C", provider: "private", model: "" });

  return (
    <Card>
      <CardHeader title="Model route lifecycle" icon={<GitCommitVertical className="size-4" aria-hidden />} count={data.data ? `${data.data.routes.length} managed` : undefined} />
      <ApiErrorBanner error={data.error} />
      {data.data && (
        <p className="-mt-1 px-5 pb-3 text-xs text-muted">
          Shadow needs a current qualification; canary needs {data.data.rules.shadow_min_runs} shadow runs at valid rate ≥ {data.data.rules.min_valid_rate};
          active needs {data.data.rules.canary_min_runs} canary runs with no invalid output, approved by a different person than the one who started the canary.
          Shadow outputs are never served or reviewed. Phases without a managed active route use their environment-configured model.
        </p>
      )}
      <ActionError error={action.error} />
      <ActionDone message={action.done} />
      {data.data && data.data.routes.length > 0 && (
        <TableWrap minWidth="min-w-[820px]" label="Managed model routes">
          <thead><tr><Th>Phase</Th><Th>Route</Th><Th>Stage</Th><Th>Shadow</Th><Th>Canary</Th><Th>Last change</Th><Th><span className="sr-only">Actions</span></Th></tr></thead>
          <tbody className="divide-y divide-line">
            {data.data.routes.map((r) => (
              <tr key={r.id}>
                <Td>{r.phase}</Td>
                <Td><Mono>{r.provider}:{r.model}</Mono></Td>
                <Td><StatusBadge status={BADGE[r.stage] ?? "unknown"} label={r.stage.replace("_", " ")} /></Td>
                <Td className="text-xs">{r.shadow.valid}/{r.shadow.runs}</Td>
                <Td className="text-xs">{r.canary.valid}/{r.canary.runs}{r.canary.invalid ? `, ${r.canary.invalid} invalid` : ""} · {r.canary_percent}%</Td>
                <Td className="text-xs text-muted">{r.changed_by} · {formatTime(r.changed_at)}</Td>
                <Td className="space-x-1 whitespace-nowrap text-right">
                  {canChange && (NEXT[r.stage] ?? []).map((to) => (
                    <Button key={to} className="px-2 py-1 text-xs" disabled={action.busy !== null}
                      onClick={() => action.run(`${r.id}-${to}`, () => post(`/v1/staff/admin/model-routes/${r.id}/stage`, { to, note: `move to ${to}` }),
                        `${r.provider}:${r.model} moved to ${to}.`)}>
                      {to}
                    </Button>
                  ))}
                  {canChange && r.stage === "active" && (
                    <Button variant="danger" className="px-2 py-1 text-xs" disabled={action.busy !== null}
                      onClick={() => window.confirm(`Roll back phase ${r.phase}?`) && action.run(`rb-${r.phase}`,
                        () => post(`/v1/staff/admin/model-routes/phases/${r.phase}/rollback`, { note: "rollback from governance" }), `Phase ${r.phase} rolled back.`)}>
                      Roll back
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
      {canChange && (
        <form className="flex flex-wrap items-end gap-3 border-t border-line px-5 py-4" onSubmit={(e) => {
          e.preventDefault();
          action.run("register", () => post("/v1/staff/admin/model-routes", form), `Registered ${form.provider}:${form.model} for phase ${form.phase}.`);
        }}>
          <Field label="Phase">
            <select value={form.phase} onChange={(e) => setForm({ ...form, phase: e.target.value })} className={`${inputClass} w-24`}>
              {["A", "B", "C", "D", "E", "F", "G", "R"].map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
          <Field label="Provider">
            <select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} className={`${inputClass} w-32`}>
              <option value="private">private</option><option value="groq">groq</option>
            </select>
          </Field>
          <Field label="Exact model">
            <input required value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} className={`${inputClass} w-72`} placeholder="qwen2.5-coder:1.5b" />
          </Field>
          <Button type="submit" variant="primary" disabled={action.busy !== null || !form.model.trim()}>Register candidate</Button>
        </form>
      )}
    </Card>
  );
}
