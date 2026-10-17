"use client";

import { post, usePoll } from "@assureops/ui/client";
import {
  ApiErrorBanner, Button, Card, CardHeader, EmptyState, Field, inputClass, LoadingState, Mono, PageHeader, SeverityBadge, StatusBadge, TableWrap, Td, Th,
} from "@assureops/ui/components";
import { formatTime } from "@assureops/ui/format";
import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";
import { ActionDone, ActionError, DutyBadge, RevisionDrift } from "@/components/staff-ui";
import { useStaffAction } from "@/lib/actions";
import { useStaff } from "@/lib/staff-context";
import type { Incident } from "@/lib/types";

function CloseForm({ incident, current, onDone, onClose, onSuccess }: {
  incident: Incident; current: Incident | undefined; onDone: () => void; onClose: () => void; onSuccess: (m: string) => void;
}) {
  const { hasRole } = useStaff();
  const [loaded] = useState(incident);
  const [note, setNote] = useState("");
  const action = useStaffAction(onDone);

  return (
    <form className="space-y-3 bg-canvas px-5 py-4" onSubmit={async (e) => {
      e.preventDefault();
      const r = await action.run("close", () => post<{ id: string; state: string }>(`/v1/staff/incidents/${loaded.id}/close`,
        { case_id: loaded.case_id, note: note.trim(), expected_revision: loaded.revision }));
      if (r) onSuccess(`Incident ${loaded.id} is ${r.state}.`);
    }}>
      <p className="text-sm">Close <span className="font-medium">{loaded.title}</span> (revision {loaded.revision}, affected cohort {loaded.cohort}).</p>
      <p className="text-xs text-muted">
        Closure needs current passing retest evidence for control {loaded.control} on a release other than {loaded.cohort}. A generic pass never closes a runtime incident.
        {(loaded.your_duty !== "reviewer" || !hasRole("senior_reviewer")) && " Only the case's independent reviewer with the senior reviewer role may close; the API will refuse otherwise."}
      </p>
      <RevisionDrift loaded={loaded.revision} current={current?.revision} what="incident" />
      <Field label="Closure note (required, min. 3 characters)">
        <textarea required minLength={3} rows={2} value={note} onChange={(e) => setNote(e.target.value)} className={inputClass} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" disabled={action.busy !== null || note.trim().length < 3}>{action.busy ? "Closing…" : "Close incident"}</Button>
        <Button onClick={onClose}>Cancel</Button>
      </div>
      <ActionError error={action.error} />
    </form>
  );
}

export default function IncidentsPage() {
  const { data, error, loading, refresh } = usePoll<Incident[]>("/v1/staff/incidents", 10000);
  const [open, setOpen] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Incident | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const openCount = data?.filter((i) => i.state === "open").length ?? 0;

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Incidents" subtitle="Verified runtime incidents on applications of cases assigned to you."
        actions={<Button onClick={refresh}><RefreshCw className="size-4" aria-hidden /> Refresh</Button>} />
      <ApiErrorBanner error={error} />
      {done && <div className="mb-4"><ActionDone message={done} /></div>}
      <Card>
        <CardHeader title="Incidents" count={data ? `${openCount} open of ${data.length}` : undefined} />
        {loading && !data ? <div className="px-5"><LoadingState label="Loading incidents…" /></div> : !data ? null : data.length === 0 ? (
          <EmptyState title="No incidents" body="Incidents appear when verified runtime events contradict a control on an assigned case." />
        ) : (
          <TableWrap minWidth="min-w-[1080px]">
            <thead><tr><Th>Severity</Th><Th>Incident</Th><Th>Case</Th><Th>Control</Th><Th>Cohort</Th><Th>Incident state</Th><Th>Closure</Th><Th>Your duty</Th><Th className="text-right">Action</Th></tr></thead>
            <tbody className="divide-y divide-line">
              {data.map((i) => (
                <Fragment key={i.id}>
                  <tr>
                    <Td><SeverityBadge severity={i.severity} /></Td>
                    <Td><p className="font-medium">{i.title}</p><Mono>{i.id}</Mono><p className="text-xs text-muted">{formatTime(i.created_at)} · rev {i.revision}</p></Td>
                    <Td><Link href={`/cases/${i.case_id}`} className="hover:underline">{i.case_title}</Link></Td>
                    <Td>{i.control}</Td>
                    <Td>{i.cohort}</Td>
                    <Td><StatusBadge status={i.state} /></Td>
                    <Td className="max-w-xs text-xs">
                      {i.closure ? <>By {i.closure.reviewer} on {i.closure.release} · {formatTime(i.closure.at)}<span className="block text-muted">“{i.closure.note}”</span></> : <span className="text-muted">—</span>}
                    </Td>
                    <Td><DutyBadge duty={i.your_duty} /></Td>
                    <Td className="text-right">
                      {i.state === "open" ? (
                        <Button className="px-2.5 py-1 text-xs" aria-expanded={open === i.id} onClick={() => {
                          if (open === i.id) { setOpen(null); return; }
                          setSnapshot(i); setDone(null); setOpen(i.id);
                        }}>{open === i.id ? "Cancel" : "Close…"}</Button>
                      ) : <span className="text-xs text-muted">Closed</span>}
                    </Td>
                  </tr>
                  {open === i.id && snapshot && (
                    <tr><td colSpan={9} className="p-0">
                      <CloseForm key={snapshot.id} incident={snapshot} current={i} onDone={refresh} onClose={() => setOpen(null)}
                        onSuccess={(m) => { setDone(m); setOpen(null); }} />
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
    </div>
  );
}
