"use client";

import { Bot, FileCheck2, ShieldCheck, UserCheck, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { api, ApiError } from "./client";
import { Mono, StatusBadge } from "./components";
import { formatTime, shortHash, timeAgo } from "./format";
import { useState } from "react";

export type Evidence = {
  id: string;
  test_id: string;
  test_name: string;
  control: string;
  control_name: string;
  claim: string;
  release: string;
  outcome: string;
  trials: number;
  passed_trials: number;
  trial_outcomes: boolean[];
  expected: string;
  observation_source: string;
  origin: string;
  collection_scope: string;
  dependency_fingerprints: Record<string, string | null>;
  evidence_hash: string | null;
  available: boolean;
  model_role: string;
  review: { reviewer: string; decision: string; note: string; at: number } | null;
  created_at: number;
  record?: unknown;
  unavailable_reason?: string;
};

/**
 * The shared evidence drawer (plan §34.3). Observed facts, test outcome, AI
 * hypotheses and reviewer decisions are shown in separate sections and never merged.
 */
export function EvidenceDrawer({ runId, onClose, path = "/v1/evidence" }: { runId: string; onClose: () => void; path?: string }) {
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    closeRef.current?.focus();
    api<Evidence>(`${path}/${runId}`).then(setEvidence).catch((e) =>
      setError(e instanceof ApiError && e.status === 403 ? `Permission denied: ${e.message}` : e.message));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCloseRef.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [runId, path]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-label="Evidence details" onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-line bg-surface shadow-xl sm:w-[560px]">
        <div className="sticky top-0 flex items-start justify-between gap-3 border-b border-line bg-surface px-5 py-4">
          <div>
            <p className="text-xs font-medium text-muted">Evidence · {evidence?.control} {evidence?.control_name}</p>
            <h2 className="mt-0.5 font-semibold">{evidence?.claim ?? "Loading…"}</h2>
          </div>
          <button ref={closeRef} onClick={onClose} className="rounded-md p-1 text-muted hover:bg-canvas" aria-label="Close evidence">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        {error && <p role="alert" className="m-5 text-sm text-red-700">{error}</p>}
        {evidence && (
          <div className="space-y-5 px-5 py-4 text-sm">
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted uppercase"><FileCheck2 className="size-4" aria-hidden />Observed facts</h3>
              <dl className="grid grid-cols-2 gap-3">
                <div><dt className="text-xs text-muted">Exact release</dt><dd className="font-medium">{evidence.release}</dd></div>
                <div><dt className="text-xs text-muted">Origin</dt><dd className="capitalize">{evidence.origin}</dd></div>
                <div className="col-span-2"><dt className="text-xs text-muted">Observation source</dt><dd>{evidence.observation_source}</dd></div>
                <div className="col-span-2"><dt className="text-xs text-muted">Collection scope</dt><dd>{evidence.collection_scope}</dd></div>
                <div><dt className="text-xs text-muted">Recorded</dt><dd>{formatTime(evidence.created_at)} ({timeAgo(evidence.created_at)})</dd></div>
                <div><dt className="text-xs text-muted">Integrity</dt><dd>{evidence.available ? <Mono>sha256 {shortHash(evidence.evidence_hash, 16)}</Mono> : <StatusBadge status="unavailable" />}
                  {evidence.available && path === "/v1/evidence" && (
                    <a className="ml-2 text-xs text-brand-700 underline" href={`/api/v1/evidence/${encodeURIComponent(evidence.id)}/download`}>Download exact bytes</a>)}</dd></div>
              </dl>
              <p className="mt-3 text-xs text-muted">Depended on (reviewed edges)</p>
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {Object.entries(evidence.dependency_fingerprints).map(([cid, fp]) => (
                  <li key={cid} className="rounded-md border border-line px-2 py-0.5 font-mono text-[11px]">{cid} · {shortHash(fp)}</li>
                ))}
                {Object.keys(evidence.dependency_fingerprints).length === 0 && <li className="text-xs text-muted">Mandatory boundary check; never reused</li>}
              </ul>
            </section>

            <section>
              <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted uppercase"><ShieldCheck className="size-4" aria-hidden />Test outcome</h3>
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={evidence.outcome} />
                <span className="text-xs text-muted">{evidence.passed_trials}/{evidence.trials} trials passed</span>
                <span className="flex gap-0.5" aria-label="Trial results">
                  {evidence.trial_outcomes.map((ok, i) => <span key={i} className={`size-2.5 rounded-sm ${ok ? "bg-brand-600" : "bg-red-600"}`} title={`Trial ${i + 1}: ${ok ? "passed" : "failed"}`} />)}
                </span>
              </div>
              <p className="mt-2"><span className="text-xs text-muted">Expected: </span>{evidence.expected}</p>
            </section>

            <section>
              <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted uppercase"><Bot className="size-4" aria-hidden />AI hypotheses</h3>
              <p className="text-muted">None. Model role: {evidence.model_role}.</p>
            </section>

            <section>
              <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted uppercase"><UserCheck className="size-4" aria-hidden />Reviewer decisions</h3>
              {evidence.review ? (
                <p><StatusBadge status={evidence.review.decision === "accept" ? "accepted" : "rejected"} /> {evidence.review.reviewer} · {formatTime(evidence.review.at)} — “{evidence.review.note}”</p>
              ) : <p className="text-muted">No reviewer decision recorded.</p>}
            </section>

            <section>
              <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">Raw evidence record</h3>
              {evidence.record ? (
                <pre className="max-h-96 overflow-auto rounded-lg border border-line bg-canvas p-3 text-[11px] leading-relaxed">{JSON.stringify(evidence.record, null, 2)}</pre>
              ) : <p className="text-muted">{evidence.unavailable_reason ?? "Unavailable."}</p>}
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}
