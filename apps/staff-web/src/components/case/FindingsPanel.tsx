"use client";

import { post } from "@assureops/ui/client";
import { Button, Card, CardHeader, EmptyState, Field, inputClass, Mono, SeverityBadge, StatusBadge, TableWrap, Td, Th } from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { TriangleAlert } from "lucide-react";
import { Fragment, useState } from "react";
import { ActionDone, ActionError, RevisionDrift } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import type { Duty, Finding } from "@/lib/types";

function DecisionForm({ caseId, finding, current, duty, onDone, onCancel, onSuccess }: {
  caseId: string; finding: Finding; current: Finding | undefined; duty: Duty; onDone: () => void; onCancel: () => void; onSuccess: (message: string) => void;
}) {
  // The revision is captured when the form opens; polling must not silently move it forward.
  const [loadedRevision] = useState(finding.revision);
  const [decision, setDecision] = useState<"confirm" | "erroneous">("confirm");
  const [note, setNote] = useState("");
  const action = useStaffAction(onDone);
  const name = `decision-${finding.id}`;

  return (
    <form className="space-y-3 bg-canvas px-5 py-4" onSubmit={async (e) => {
      e.preventDefault();
      const saved = await action.run("decide", () => post<Finding>(`/v1/staff/cases/${caseId}/findings/${finding.id}/reviews`,
        { decision, note: note.trim(), expected_revision: loadedRevision }));
      if (saved) onSuccess(`Recorded “${decision}” on ${finding.title}; finding is now ${saved.state} (revision ${saved.revision}).`);
    }}>
      <p className="text-sm">Independent reviewer decision on <span className="font-medium">{finding.title}</span> (revision {loadedRevision}).</p>
      {duty !== "reviewer" && <p className="text-xs text-amber-700">Your duty on this case is {duty}. Only the assigned independent reviewer may decide; the API will refuse otherwise.</p>}
      <RevisionDrift loaded={loadedRevision} current={current?.revision} what="finding" />
      <fieldset>
        <legend className="mb-1 text-xs font-medium text-muted">Decision</legend>
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="radio" name={name} checked={decision === "confirm"} onChange={() => setDecision("confirm")} /> Confirm — the finding stands (stays open)</label>
          <label className="flex items-center gap-2"><input type="radio" name={name} checked={decision === "erroneous"} onChange={() => setDecision("erroneous")} /> Erroneous — audited determination, resolves it</label>
        </div>
      </fieldset>
      <Field label="Note (required, min. 3 characters)">
        <textarea required minLength={3} rows={2} value={note} onChange={(e) => setNote(e.target.value)} className={inputClass} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" disabled={action.busy !== null || note.trim().length < 3}>{action.busy ? "Recording…" : "Record decision"}</Button>
        <Button onClick={onCancel}>Close</Button>
      </div>
      <ActionError error={action.error} />
    </form>
  );
}

export function FindingsPanel({ caseId, findings, duty, onChange }: { caseId: string; findings: Finding[]; duty: Duty; onChange: () => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Finding | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const unresolved = findings.filter((f) => f.state !== "resolved").length;

  return (
    <Card className="mb-5">
      <CardHeader title="Findings" icon={<TriangleAlert className="size-4" aria-hidden />} count={`${unresolved} unresolved of ${findings.length}`} />
      {done && <div className="px-5 pb-3"><ActionDone message={done} /></div>}
      {findings.length === 0 ? <EmptyState title="No findings" body="Findings appear when a test fails or a verified runtime violation contradicts a control." /> : (
        <TableWrap minWidth="min-w-[960px]">
          <thead><tr><Th>Severity</Th><Th>Finding</Th><Th>Control</Th><Th>Finding state</Th><Th>Source</Th><Th>Releases</Th><Th>Revision</Th><Th className="text-right">Reviewer decision</Th></tr></thead>
          <tbody className="divide-y divide-line">
            {findings.map((f) => (
              <Fragment key={f.id}>
                <tr>
                  <Td><SeverityBadge severity={f.severity} /></Td>
                  <Td>
                    <p className="font-medium">{f.title}</p>
                    <p className="text-xs text-muted">{f.description}</p>
                    {f.reviews && f.reviews.length > 0 && (
                      <ul className="mt-1 space-y-0.5 text-xs text-muted">
                        {f.reviews.map((r, i) => <li key={i}>{r.decision} by {r.reviewer} ({r.reviewer_kind}) · {formatTime(r.at)} — “{r.note}”</li>)}
                      </ul>
                    )}
                  </Td>
                  <Td className="whitespace-nowrap">{f.control} {f.control_name}</Td>
                  <Td><StatusBadge status={f.state} /></Td>
                  <Td className="whitespace-nowrap">{f.source === "runtime" ? "Verified in operation" : <>Test <Mono>{f.test_id}</Mono></>}</Td>
                  <Td className="whitespace-nowrap text-muted">{f.first_release ?? "—"}{f.last_release && f.last_release !== f.first_release ? ` → ${f.last_release}` : ""}</Td>
                  <Td>{f.revision}</Td>
                  <Td className="text-right">
                    <Button className="px-2.5 py-1 text-xs" aria-expanded={open === f.id} onClick={() => {
                      if (open === f.id) { setOpen(null); return; }
                      setSnapshot(f);
                      setDone(null);
                      setOpen(f.id);
                    }}>{open === f.id ? "Close" : "Decide"}</Button>
                  </Td>
                </tr>
                {open === f.id && snapshot && (
                  <tr><td colSpan={8} className="p-0">
                    <DecisionForm key={snapshot.id} caseId={caseId} finding={snapshot} current={f} duty={duty} onDone={onChange} onCancel={() => setOpen(null)}
                      onSuccess={(m) => { setDone(m); setOpen(null); }} />
                  </td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </TableWrap>
      )}
    </Card>
  );
}
