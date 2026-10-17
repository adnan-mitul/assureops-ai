"use client";

import { post } from "@assureops/ui/client";
import { Button, Card, CardHeader, Field, inputClass, Mono, Notice, SeverityBadge, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { EvidenceDrawer } from "@assureops/ui/evidence-drawer";
import { formatTime } from "@assureops/ui/format";
import { FileCheck2 } from "lucide-react";
import { Fragment, useCallback, useState } from "react";
import { ActionDone, ActionError } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import type { Duty, Readiness, TestState } from "@/lib/types";

function SemanticReviewForm({ caseId, test, onDone, onCancel, onSuccess }: {
  caseId: string; test: TestState; onDone: () => void; onCancel: () => void; onSuccess: (message: string) => void;
}) {
  const [decision, setDecision] = useState<"accept" | "reject">("accept");
  const [note, setNote] = useState("");
  const action = useStaffAction(onDone);
  const name = `semantic-${test.test_id}`;

  return (
    <form className="space-y-3 bg-canvas px-5 py-4" onSubmit={async (e) => {
      e.preventDefault();
      const ok = await action.run("review", () => post(`/v1/staff/cases/${caseId}/evidence-reviews`, { run_id: test.run_id, decision, note: note.trim() }));
      if (ok) onSuccess(`Recorded “${decision}” for ${test.test_id}; readiness recomputes from the reviewed evidence.`);
    }}>
      <p className="text-sm">Semantic evidence for <span className="font-medium">{test.name}</span> (run <Mono>{test.run_id}</Mono>) needs a human decision. Open the evidence first and judge the observation, not the summary.</p>
      <fieldset>
        <legend className="mb-1 text-xs font-medium text-muted">Decision</legend>
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="radio" name={name} checked={decision === "accept"} onChange={() => setDecision("accept")} /> Accept — evidence supports the claim</label>
          <label className="flex items-center gap-2"><input type="radio" name={name} checked={decision === "reject"} onChange={() => setDecision("reject")} /> Reject — evidence does not support it</label>
        </div>
      </fieldset>
      <Field label="Reviewer note (required, min. 3 characters)">
        <textarea required minLength={3} rows={2} value={note} onChange={(e) => setNote(e.target.value)} className={inputClass} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" disabled={action.busy !== null || note.trim().length < 3}>{action.busy ? "Recording…" : "Record decision"}</Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
      <ActionError error={action.error} />
    </form>
  );
}

export function TestEvidence({ caseId, readiness, duty, onChange }: { caseId: string; readiness: Readiness; duty: Duty; onChange: () => void }) {
  const [drawer, setDrawer] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const pending = readiness.tests.filter((t) => t.result === "review_required" && t.run_id);

  return (
    <Card className="mb-5">
      <CardHeader title="Test evidence" icon={<FileCheck2 className="size-4" aria-hidden />}
        count={`${readiness.counts.tests_current_passing}/${readiness.counts.tests_total} current and passing · ${pending.length} awaiting semantic review`} />
      {done && <div className="px-5 pb-3"><ActionDone message={done} /></div>}
      {pending.length > 0 && (
        <div className="px-5 pb-3">
          <Notice tone="warn">{pending.length} semantic result{pending.length === 1 ? "" : "s"} require human review before the control can count as supported. No model route is qualified, so these are never auto-accepted.</Notice>
        </div>
      )}
      <TableWrap minWidth="min-w-[1100px]">
        <thead>
          <tr><Th>Test</Th><Th>Control</Th><Th>Severity</Th><Th>Result</Th><Th>Evidence validity</Th><Th>Release</Th><Th>Trials</Th><Th>Reused</Th><Th>Depends on</Th><Th className="text-right">Actions</Th></tr>
        </thead>
        <tbody className="divide-y divide-line">
          {readiness.tests.map((t) => (
            <Fragment key={t.test_id}>
              <tr>
                <Td><p>{t.name}</p><Mono>{t.test_id}</Mono>{t.review && <p className="text-xs text-muted">Reviewed: {t.review.decision} by {t.review.reviewer}</p>}</Td>
                <Td>{t.control}</Td>
                <Td><SeverityBadge severity={t.severity} /></Td>
                <Td><StatusBadge status={t.result} /></Td>
                <Td><StatusBadge status={t.validity} /></Td>
                <Td className="whitespace-nowrap text-muted">{t.release ?? "—"}{t.at ? <span className="block text-[11px]">{formatTime(t.at)}</span> : null}</Td>
                <Td className="whitespace-nowrap">{t.trials != null ? `${t.passed_trials ?? 0}/${t.trials}` : "—"}</Td>
                <Td>{t.reused ? <StatusBadge status="reused" /> : <span className="text-xs text-muted">No</span>}</Td>
                <Td>{t.depends_on.length ? <span className="font-mono text-[11px] text-muted">{t.depends_on.join(", ")}</span> : <span className="text-xs text-muted">No edges (never reused)</span>}</Td>
                <Td className="text-right">
                  <div className="flex flex-wrap justify-end gap-2">
                    {t.run_id ? <button className="text-xs font-medium whitespace-nowrap text-brand-700 hover:underline" onClick={() => setDrawer(t.run_id!)}>Open evidence</button>
                      : <span className="text-xs text-muted">No run yet</span>}
                    {t.result === "review_required" && t.run_id && (
                      <button className="text-xs font-medium whitespace-nowrap text-amber-700 hover:underline" aria-expanded={reviewing === t.test_id}
                        onClick={() => { setDone(null); setReviewing(reviewing === t.test_id ? null : t.test_id); }}>Review semantic result</button>
                    )}
                  </div>
                </Td>
              </tr>
              {reviewing === t.test_id && (
                <tr><td colSpan={10} className="p-0"><SemanticReviewForm caseId={caseId} test={t} onDone={onChange} onCancel={() => setReviewing(null)}
                  onSuccess={(m) => { setDone(m); setReviewing(null); }} /></td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </TableWrap>
      <p className="border-t border-line px-5 py-3 text-xs text-muted">
        Evidence is read through this case&apos;s grant ({duty === "analyst" ? "analyst" : "independent reviewer"} duty); each read is audited.
      </p>
      {drawer && <EvidenceDrawer runId={drawer} onClose={closeDrawer} path={`/v1/staff/cases/${caseId}/evidence`} />}
    </Card>
  );
}
