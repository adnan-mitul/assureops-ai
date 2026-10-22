"use client";

import { newIdempotencyKey, post, useAction } from "@assureops/ui/client";
import { Button, inputClass } from "@assureops/ui/components";
import { FlaskConical, Loader2, RefreshCw, Rocket, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useApp } from "@/lib/app-context";

/** Submit a release, schedule the change-driven retest plan or a full assessment. */
export function ReleaseActions({ applicationId, changeId, running, onChange, showDemo = true }: {
  applicationId: string; changeId?: string | null; running: boolean; onChange: () => void; showDemo?: boolean;
}) {
  const { canWrite } = useApp();
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [commit, setCommit] = useState("");  // the Git commit of this release; the CI release gate matches it exactly
  const commitValid = commit === "" || /^[0-9a-f]{7,40}$/.test(commit);
  if (!canWrite) {
    return <p className="text-xs text-muted">Your role can view results but cannot submit releases or start assessments.</p>;
  }
  const disabled = !!busy || running;

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {showDemo && (
          <div className="flex items-center gap-1 rounded-lg border border-dashed border-line bg-surface px-2 py-1"
            title="Demo only: switch the synthetic target to another release, then submit it">
            <Rocket className="size-3.5 text-muted" aria-hidden />
            <span className="mr-1 text-xs text-muted">Demo deploy</span>
            {["R1", "R2", "R3"].map((r) => (
              <button key={r} disabled={disabled} onClick={() => run(r, () => post("/v1/demo/deploy", { application_id: applicationId, release: r }), onChange)}
                className="rounded-md px-2 py-0.5 text-xs font-medium hover:bg-canvas disabled:opacity-50" aria-label={`Deploy demo release ${r}`}>
                {busy === r ? <Loader2 className="size-3 animate-spin" aria-hidden /> : r}
              </button>
            ))}
          </div>
        )}
        <input aria-label="Commit SHA of this release (optional)" placeholder="commit SHA (optional)" value={commit}
          onChange={(e) => setCommit(e.target.value.trim().toLowerCase())}
          className={`${inputClass} w-56 py-1.5 font-mono text-xs ${commitValid ? "" : "border-red-400"}`} />
        <Button disabled={disabled || !commitValid} onClick={() => run("submit", () => post(`/v1/applications/${applicationId}/releases`,
          commit ? { source_commit: commit } : {}), onChange)}>
          <Upload className="size-4" aria-hidden /> Submit release
        </Button>
        {changeId && (
          <Button disabled={disabled} onClick={() => run("retest", async () => {
            const job = await post<{ id: string }>(`/v1/changes/${changeId}/retests`, {}, newIdempotencyKey());
            router.push(`/assessments/${job.id}`);
          }, onChange)}>
            {busy === "retest" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <RefreshCw className="size-4" aria-hidden />} Run required retests
          </Button>
        )}
        <Button variant="primary" disabled={disabled} onClick={() => run("full", async () => {
          const job = await post<{ id: string }>("/v1/assessments", { application_id: applicationId, scope: "full" }, newIdempotencyKey());
          router.push(`/assessments/${job.id}`);
        }, onChange)}>
          <FlaskConical className="size-4" aria-hidden /> {running ? "Assessment running…" : "Full assessment"}
        </Button>
      </div>
      {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    </div>
  );
}
