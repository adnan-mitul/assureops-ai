"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

function csrfToken(): string {
  // Each portal names its CSRF cookie after its client ID (NEXT_PUBLIC_PORTAL_ID).
  const name = `ao_csrf_${process.env.NEXT_PUBLIC_PORTAL_ID}`;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]+)`));
  return match ? decodeURIComponent(match[1]) : "";
}

/** Calls the portal's own BFF; the browser never holds an access token. */
export async function api<T>(path: string, init: RequestInit & { idempotencyKey?: string } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (init.body) headers["Content-Type"] = "application/json";
  if (init.method && init.method !== "GET") headers["x-csrf-token"] = csrfToken();
  if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;
  const response = await fetch(`/api${path}`, { ...init, headers, cache: "no-store" });
  if (response.status === 401) {
    window.location.href = `/auth/login?returnTo=${encodeURIComponent(window.location.pathname + window.location.search)}`; // keep the query (e.g. an invitation token)
    throw new ApiError(401, "unauthenticated", "Redirecting to sign in…");
  }
  if (!response.ok) {
    let code = "error";
    let message = response.statusText;
    try {
      const body = await response.json();
      code = body.detail?.code ?? code;
      message = body.detail?.message ?? (typeof body.detail === "string" ? body.detail : message);
    } catch {}
    throw new ApiError(response.status, code, message);
  }
  return response.json() as Promise<T>;
}

export const post = <T,>(path: string, body: unknown = {}, idempotencyKey?: string) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body), idempotencyKey });

export const put = <T,>(path: string, body: unknown = {}) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });

/** Loads authoritative state and refetches on an interval; reconnects simply reload. */
export function usePoll<T>(path: string | null, intervalMs = 4000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const active = useRef(true);

  const refresh = useCallback(async () => {
    if (!path) return;
    try {
      const result = await api<T>(path);
      if (active.current) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (active.current) setError(e instanceof ApiError ? e : new ApiError(0, "network", String(e)));
    } finally {
      if (active.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    active.current = true;
    const first = setTimeout(refresh, 0);
    const timer = intervalMs > 0 ? setInterval(refresh, intervalMs) : undefined;
    return () => {
      active.current = false;
      clearTimeout(first);
      if (timer) clearInterval(timer);
    };
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}

/** Runs a mutation with busy and error state, then refreshes callers. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, after?: () => void): Promise<T | undefined> => {
    setBusy(key);
    setError(null);
    setApiError(null);
    try {
      const result = await fn();
      after?.();
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setApiError(e instanceof ApiError ? e : null);
      return undefined;
    } finally {
      setBusy(null);
    }
  }, []);
  return { busy, error, apiError, run, setError };
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
