"use client";

import { post, usePoll } from "@assureops/ui/client";
import { Button, Card, Notice } from "@assureops/ui/components";
import { CircleCheck, ClipboardCheck, PlugZap, ShieldCheck } from "lucide-react";
import { ActionDone, ActionError } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import type { CaseDetail } from "@/lib/types";

type Profile = { revision: number; status: string; source: string; proposed_by: string; tests: { id: string }[] };
type Prepared = { verification: { status: string; checks: { id: string; status: string; detail: string }[] }; release: { version: string } | null };

/** The simple path for a submitted application: developer verifies and plans, the admin activates, then run and report as usual. */
export function SetupPanel({ data, onChange }: { data: CaseDetail; onChange: () => void }) {
  const profiles = usePoll<Profile[]>(`/v1/staff/cases/${data.id}/profiles`, 0);
  const action = useStaffAction(() => { profiles.refresh(); onChange(); });
  const developer = data.your_duty === "analyst";
  const admin = data.your_duty === "reviewer";
  const proposed = (profiles.data ?? []).filter((p) => p.status === "proposed");
  const active = (profiles.data ?? []).find((p) => p.status === "active");

  const prepare = () => action.run("prepare", async () => {
    const r = await post<Prepared>(`/v1/staff/cases/${data.id}/prepare`, {});
    const failed = r.verification.checks.filter((c) => c.status === "fail").map((c) => `${c.id}: ${c.detail}`);
    if (failed.length) throw new Error(`Connection not verified. ${failed.join("; ")}`);
    return r;
  }, "Connection verified and the running release collected.");

  return (
    <Card className="mb-5 p-5">
      <h2 className="text-[15px] font-semibold">Test setup</h2>
      <p className="mt-1 text-xs text-muted">
        Developer: verify the customer&apos;s application and build its test plan. Admin: review and activate the plan. Then run the
        assessment, draft the report, and the admin publishes it to the customer.
      </p>
      <ol className="mt-3 grid gap-3 md:grid-cols-3">
        <li className="rounded-lg border border-line p-3 text-sm">
          <p className="flex items-center gap-2 font-medium"><PlugZap className="size-4" aria-hidden /> 1. Verify and collect</p>
          <p className="mt-1 text-xs text-muted">Checks the URL, health, manifest and test account, then records the running release.</p>
          <Button className="mt-2" disabled={!developer || action.busy !== null} onClick={prepare}>Verify and collect</Button>
        </li>
        <li className="rounded-lg border border-line p-3 text-sm">
          <p className="flex items-center gap-2 font-medium"><ClipboardCheck className="size-4" aria-hidden /> 2. Build test plan</p>
          <p className="mt-1 text-xs text-muted">Proposes catalogue tests from what the customer declared at submission.</p>
          <Button className="mt-2" disabled={!developer || action.busy !== null}
            onClick={() => action.run("plan", () => post(`/v1/staff/cases/${data.id}/profiles/baseline`, {}), "Test plan proposed; the admin activates it.")}>
            Build test plan
          </Button>
        </li>
        <li className="rounded-lg border border-line p-3 text-sm">
          <p className="flex items-center gap-2 font-medium"><ShieldCheck className="size-4" aria-hidden /> 3. Admin activates</p>
          {active && <p className="mt-1 flex items-center gap-1 text-xs text-emerald-700"><CircleCheck className="size-3.5" aria-hidden />
            Plan revision {active.revision} active ({active.tests.length} tests).</p>}
          {proposed.length === 0 && !active && <p className="mt-1 text-xs text-muted">No plan proposed yet.</p>}
          {proposed.map((p) => (
            <div key={p.revision} className="mt-2">
              <p className="text-xs text-muted">Revision {p.revision} by {p.proposed_by}: {p.tests.length} tests</p>
              <Button className="mt-1" variant="primary" disabled={!admin || action.busy !== null}
                onClick={() => action.run(`act-${p.revision}`, () => post(`/v1/staff/cases/${data.id}/profile-reviews`,
                  { revision: p.revision, decision: "activate", note: "Reviewed the proposed test plan" }), "Test plan activated.")}>
                Activate plan
              </Button>
            </div>))}
        </li>
      </ol>
      <div className="mt-3 space-y-2">
        {!developer && !admin && <Notice tone="warn">You are not assigned to this case.</Notice>}
        <ActionError error={action.error} />
        <ActionDone message={action.done} />
      </div>
    </Card>
  );
}
