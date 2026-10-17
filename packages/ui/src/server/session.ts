import "server-only";
import { randomBytes } from "node:crypto";

export type Session = {
  id: string;
  accessToken: string;
  refreshToken: string;
  idToken: string;
  expiresAt: number;
  username: string;
  workspaceId?: string;
  csrf: string;
};

export type PendingLogin = { state: string; verifier: string; returnTo: string; createdAt: number };

type Store = { sessions: Map<string, Session>; pending: Map<string, PendingLogin> };

// Server-side session store: the browser only ever holds an opaque HttpOnly session ID.
const g = globalThis as unknown as { __assureopsSessions?: Store };
const store: Store = (g.__assureopsSessions ??= { sessions: new Map(), pending: new Map() });

// Cookie names are per portal: browsers do not isolate cookies by port, so two portals on one host must not share names.
export const cookieNames = (portalId: string) => ({
  session: `ao_session_${portalId}`,
  csrf: `ao_csrf_${portalId}`,
  login: `ao_login_${portalId}`,
});

export function randomId(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

export function getSession(id: string | undefined): Session | undefined {
  return id ? store.sessions.get(id) : undefined;
}

export function saveSession(session: Session) {
  store.sessions.set(session.id, session);
}

export function deleteSession(id: string | undefined) {
  if (id) store.sessions.delete(id);
}

export function savePending(id: string, pending: PendingLogin) {
  for (const [key, value] of store.pending) {
    if (Date.now() - value.createdAt > 10 * 60_000) store.pending.delete(key);
  }
  store.pending.set(id, pending);
}

export function takePending(id: string | undefined): PendingLogin | undefined {
  if (!id) return undefined;
  const pending = store.pending.get(id);
  store.pending.delete(id);
  return pending && Date.now() - pending.createdAt < 10 * 60_000 ? pending : undefined;
}
