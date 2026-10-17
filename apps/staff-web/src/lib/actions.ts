"use client";

import { ApiError } from "@assureops/ui/client";
import { useCallback, useState } from "react";

/**
 * Runs a staff mutation and keeps the full ApiError (status and code), so the
 * page can tell permission, separation-of-duties and stale-revision refusals
 * apart. On 409 the caller's reload runs so the user sees the current object.
 */
export function useStaffAction(reload?: () => void) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const run = useCallback(
    async <T,>(key: string, fn: () => Promise<T>, success?: string): Promise<T | undefined> => {
      setBusy(key);
      setError(null);
      setDone(null);
      try {
        const result = await fn();
        if (success) setDone(success);
        reload?.();
        return result;
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError(0, "network", e instanceof Error ? e.message : String(e));
        setError(err);
        if (err.status === 409) reload?.();
        return undefined;
      } finally {
        setBusy(null);
      }
    },
    [reload],
  );

  const clear = useCallback(() => {
    setError(null);
    setDone(null);
  }, []);

  return { busy, error, done, run, clear };
}
