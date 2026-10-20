import "server-only";
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";
import { createClient } from "redis";

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

// Server-side session store in Redis: survives portal restarts and scales across instances. The browser only
// holds an opaque HttpOnly session ID; tokens are encrypted at rest (AES-256-GCM) with a server-only key.
const SESSION_TTL_SECONDS = 12 * 3600;
const PENDING_TTL_SECONDS = 600;

type RedisClient = ReturnType<typeof createClient>;
const g = globalThis as unknown as { __assureopsRedis?: Promise<RedisClient> };

function redis(): Promise<RedisClient> {
  g.__assureopsRedis ??= (async () => {
    const client = createClient({ url: process.env.SESSION_REDIS_URL ?? "redis://127.0.0.1:6391/1" });
    client.on("error", () => undefined); // surfaced per request as a failed lookup, never as a signed-in state
    await client.connect();
    return client;
  })();
  return g.__assureopsRedis;
}

function key(): Buffer {
  const secret = process.env.SESSION_ENCRYPTION_KEY;
  if (!secret) throw new Error("SESSION_ENCRYPTION_KEY is not configured");
  return createHash("sha256").update(secret).digest();
}

function seal(value: unknown): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(), iv);
  const data = Buffer.concat([cipher.update(JSON.stringify(value), "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), data]).toString("base64url");
}

function open<T>(sealed: string | null): T | undefined {
  if (!sealed) return undefined;
  try {
    const raw = Buffer.from(sealed, "base64url");
    const decipher = createDecipheriv("aes-256-gcm", key(), raw.subarray(0, 12));
    decipher.setAuthTag(raw.subarray(12, 28));
    return JSON.parse(Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]).toString("utf8")) as T;
  } catch {
    return undefined; // tampered or written with another key: treated as no session
  }
}

// Cookie names are per portal: browsers do not isolate cookies by port, so two portals on one host must not share names.
export const cookieNames = (portalId: string) => ({
  session: `ao_session_${portalId}`,
  csrf: `ao_csrf_${portalId}`,
  login: `ao_login_${portalId}`,
});

const prefix = () => `ao:${process.env.OIDC_CLIENT_ID ?? "portal"}`;

export function randomId(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

export async function getSession(id: string | undefined): Promise<Session | undefined> {
  if (!id) return undefined;
  try {
    return open<Session>(await (await redis()).get(`${prefix()}:session:${id}`));
  } catch {
    return undefined;
  }
}

export async function saveSession(session: Session) {
  await (await redis()).set(`${prefix()}:session:${session.id}`, seal(session), { EX: SESSION_TTL_SECONDS });
}

export async function deleteSession(id: string | undefined) {
  if (id) await (await redis()).del(`${prefix()}:session:${id}`);
}

export async function savePending(id: string, pending: PendingLogin) {
  await (await redis()).set(`${prefix()}:pending:${id}`, seal(pending), { EX: PENDING_TTL_SECONDS });
}

export async function takePending(id: string | undefined): Promise<PendingLogin | undefined> {
  if (!id) return undefined;
  const client = await redis();
  const sealed = await client.getDel(`${prefix()}:pending:${id}`); // single use: a replayed callback finds nothing
  const pending = open<PendingLogin>(sealed);
  return pending && Date.now() - pending.createdAt < PENDING_TTL_SECONDS * 1000 ? pending : undefined;
}
