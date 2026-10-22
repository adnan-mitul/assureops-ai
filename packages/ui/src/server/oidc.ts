import "server-only";
import { createHash } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { type Session, cookieNames, deleteSession, getSession, randomId, saveSession, savePending, takePending } from "./session";

export type PortalConfig = {
  issuer: string;
  clientId: string;
  clientSecret: string;
  origin: string;
  apiUrl: string;
  /** Path prefixes this portal may proxy to the API; anything else is refused. */
  allowedPrefixes: string[];
  deniedPrefixes?: string[];
  /** Always ask for credentials instead of reusing an existing identity-provider session (staff portal). */
  forceLogin?: boolean;
};

const secure = false; // local development over http; production sets Secure cookies behind HTTPS

function tokenEndpoint(c: PortalConfig) {
  return `${c.issuer}/protocol/openid-connect/token`;
}

function safeReturnTo(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

export function loginHandler(c: PortalConfig) {
  return async (request: NextRequest) => {
    const state = randomId(24);
    const verifier = randomId(48);
    const challenge = createHash("sha256").update(verifier).digest("base64url");
    const loginId = randomId(24);
    await savePending(loginId, { state, verifier, returnTo: safeReturnTo(request.nextUrl.searchParams.get("returnTo")), createdAt: Date.now() });
    const url = new URL(`${c.issuer}/protocol/openid-connect/auth`);
    url.search = new URLSearchParams({
      client_id: c.clientId, response_type: "code", scope: "openid profile email", redirect_uri: `${c.origin}/auth/callback`,
      state, code_challenge: challenge, code_challenge_method: "S256", ...(c.forceLogin ? { prompt: "login" } : {}),
    }).toString();
    const response = NextResponse.redirect(url);
    response.cookies.set(cookieNames(c.clientId).login, loginId, { httpOnly: true, sameSite: "lax", secure, path: "/auth", maxAge: 600 });
    return response;
  };
}

async function tokenRequest(c: PortalConfig, body: Record<string, string>) {
  const response = await fetch(tokenEndpoint(c), {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: `Basic ${Buffer.from(`${c.clientId}:${c.clientSecret}`).toString("base64")}`,
    },
    body: new URLSearchParams(body),
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`token endpoint returned ${response.status}`);
  return response.json() as Promise<{ access_token: string; refresh_token: string; id_token: string; expires_in: number }>;
}

function claims(jwt: string): Record<string, unknown> {
  return JSON.parse(Buffer.from(jwt.split(".")[1], "base64url").toString());
}

export function callbackHandler(c: PortalConfig) {
  return async (request: NextRequest) => {
    const names = cookieNames(c.clientId);
    const pending = await takePending(request.cookies.get(names.login)?.value);
    const state = request.nextUrl.searchParams.get("state");
    const code = request.nextUrl.searchParams.get("code");
    if (!pending || !code || state !== pending.state) {
      return NextResponse.redirect(new URL("/auth/login", c.origin));
    }
    const tokens = await tokenRequest(c, {
      grant_type: "authorization_code", code, redirect_uri: `${c.origin}/auth/callback`, code_verifier: pending.verifier,
    });
    const session: Session = {
      id: randomId(), accessToken: tokens.access_token, refreshToken: tokens.refresh_token, idToken: tokens.id_token,
      expiresAt: Date.now() + tokens.expires_in * 1000, username: String(claims(tokens.id_token).preferred_username ?? ""), csrf: randomId(24),
    };
    await saveSession(session);
    const response = NextResponse.redirect(new URL(pending.returnTo, c.origin));
    response.cookies.set(names.session, session.id, { httpOnly: true, sameSite: "lax", secure, path: "/" });
    response.cookies.set(names.csrf, session.csrf, { httpOnly: false, sameSite: "strict", secure, path: "/" });
    response.cookies.delete(names.login);
    return response;
  };
}

export function logoutHandler(c: PortalConfig) {
  return async (request: NextRequest) => {
    const names = cookieNames(c.clientId);
    const session = await getSession(request.cookies.get(names.session)?.value);
    const csrf = (await request.formData().catch(() => null))?.get("csrf");
    if (session && csrf !== session.csrf) return new NextResponse("CSRF check failed", { status: 403 });
    await deleteSession(session?.id);
    const url = new URL(`${c.issuer}/protocol/openid-connect/logout`);
    url.search = new URLSearchParams({ post_logout_redirect_uri: `${c.origin}/`, client_id: c.clientId, ...(session ? { id_token_hint: session.idToken } : {}) }).toString();
    const response = NextResponse.redirect(url, 303);
    response.cookies.delete(names.session);
    response.cookies.delete(names.csrf);
    return response;
  };
}

async function freshToken(c: PortalConfig, session: Session): Promise<Session | null> {
  if (session.expiresAt - Date.now() > 30_000) return session;
  try {
    const tokens = await tokenRequest(c, { grant_type: "refresh_token", refresh_token: session.refreshToken });
    const updated = { ...session, accessToken: tokens.access_token, refreshToken: tokens.refresh_token ?? session.refreshToken,
      idToken: tokens.id_token ?? session.idToken, expiresAt: Date.now() + tokens.expires_in * 1000 };
    await saveSession(updated);
    return updated;
  } catch {
    await deleteSession(session.id);
    return null;
  }
}

/** Backend-for-frontend proxy: attaches the user-scoped token server-side and enforces CSRF on mutations. */
export function proxyHandler(c: PortalConfig) {
  return async (request: NextRequest, context: { params: Promise<{ path: string[] }> }) => {
    const { path } = await context.params;
    const target = path.join("/");
    if (!c.allowedPrefixes.some((p) => target.startsWith(p)) || c.deniedPrefixes?.some((p) => target.startsWith(p))) {
      return NextResponse.json({ detail: { code: "forbidden", message: "not available from this portal" } }, { status: 403 });
    }
    const stored = await getSession(request.cookies.get(cookieNames(c.clientId).session)?.value);
    if (!stored) return NextResponse.json({ detail: { code: "unauthenticated", message: "sign in required" } }, { status: 401 });
    if (request.method !== "GET" && request.headers.get("x-csrf-token") !== stored.csrf) {
      return NextResponse.json({ detail: { code: "csrf", message: "request rejected: missing or invalid CSRF token" } }, { status: 403 });
    }
    const session = await freshToken(c, stored);
    if (!session) return NextResponse.json({ detail: { code: "unauthenticated", message: "session expired" } }, { status: 401 });

    const headers: Record<string, string> = { Authorization: `Bearer ${session.accessToken}` };
    const contentType = request.headers.get("content-type");
    if (contentType) headers["Content-Type"] = contentType;
    for (const name of ["idempotency-key", "x-workspace-id"]) {
      const value = request.headers.get(name);
      if (value) headers[name] = value;
    }
    const upstream = await fetch(`${c.apiUrl}/${target}${request.nextUrl.search}`, {
      method: request.method, headers, body: request.method === "GET" ? undefined : await request.text(), cache: "no-store",
    });
    const body = await upstream.arrayBuffer(); // binary-safe: evidence bundles are zip files
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json", "Cache-Control": "private, no-store",
        ...(upstream.headers.get("content-disposition") ? { "Content-Disposition": upstream.headers.get("content-disposition") as string } : {}),
        ...(upstream.headers.get("x-evidence-sha256") ? { "X-Evidence-SHA256": upstream.headers.get("x-evidence-sha256") as string } : {}),
      },
    });
  };
}

export function sessionInfoHandler(portalId: string) {
  return async (request: NextRequest) => {
    const session = await getSession(request.cookies.get(cookieNames(portalId).session)?.value);
    return NextResponse.json(session ? { signedIn: true, username: session.username } : { signedIn: false }, {
      headers: { "Cache-Control": "private, no-store" },
    });
  };
}
