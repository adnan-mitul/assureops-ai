"use client";

import clsx from "clsx";
import { Bell, LogOut, Search, ShieldCheck, Zap, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, useState, type ReactNode } from "react";

export type NavItem = { href: string; label: string; icon: LucideIcon };

function NavLinks({ items, pathname }: { items: NavItem[]; pathname: string | null }) {
  return (
    <ul className="space-y-0.5">
      {items.map(({ href, label, icon: Icon }) => {
        const active = pathname !== null && (pathname === href || pathname.startsWith(`${href}/`));
        return (
          <li key={href}>
            <Link href={href} aria-current={active ? "page" : undefined}
              className={clsx("flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                active ? "bg-brand-50 font-semibold text-brand-700" : "text-gray-600 hover:bg-canvas hover:text-ink")}>
              <Icon className="size-[18px]" aria-hidden />
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function ActiveNav({ items }: { items: NavItem[] }) {
  return <NavLinks items={items} pathname={usePathname()} />;
}

export function Sidebar({ portal, items, footer, home }: { portal: string; items: NavItem[]; footer?: ReactNode; home: string }) {
  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-surface lg:flex">
      <Link href={home} className="flex h-16 items-center gap-2.5 border-b border-line px-5">
        <span className="grid size-9 place-items-center rounded-lg bg-brand-50 text-brand-700"><ShieldCheck className="size-5" aria-hidden /></span>
        <span className="text-lg font-bold tracking-tight">AssureOps <span className="text-brand-700">AI</span></span>
      </Link>
      <nav className="flex-1 overflow-y-auto px-3 py-4" aria-label="Main">
        <p className="px-3 pb-2 text-xs font-medium text-muted">{portal}</p>
        <Suspense fallback={<NavLinks items={items} pathname={null} />}>
          <ActiveNav items={items} />
        </Suspense>
        {footer}
      </nav>
      <div className="m-3 rounded-xl bg-brand-50 p-4">
        <Zap className="size-5 text-brand-700" aria-hidden />
        <p className="mt-2 text-sm font-semibold text-brand-800">Secure AI. Confident releases.</p>
        <p className="mt-1 text-xs leading-relaxed text-brand-800/80">Evidence-backed readiness within a tested boundary. Not a certification.</p>
      </div>
    </aside>
  );
}

export function MobileNav({ items }: { items: NavItem[] }) {
  return (
    <nav aria-label="Main" className="flex gap-1 overflow-x-auto border-b border-line bg-surface px-4 py-2 lg:hidden">
      {items.map(({ href, label }) => (
        <Link key={href} href={href} className="rounded-md px-2.5 py-1 text-xs whitespace-nowrap text-gray-600 hover:bg-canvas">{label}</Link>
      ))}
    </nav>
  );
}

function csrf(): string {
  const name = `ao_csrf_${process.env.NEXT_PUBLIC_PORTAL_ID}`;
  const match = typeof document !== "undefined" ? document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]+)`)) : null;
  return match ? decodeURIComponent(match[1]) : "";
}

export function Topbar({ user, subtitle, alerts, alertsHref, searchHref, searchPlaceholder = "Search findings, controls, tests…" }: {
  user: string | null; subtitle: string; alerts: number; alertsHref: string; searchHref: string; searchPlaceholder?: string;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [token, setToken] = useState("");
  useEffect(() => setToken(csrf()), []);
  const initials = (user ?? "?").split(/[@.\s]/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center gap-4 border-b border-line bg-surface/95 px-4 backdrop-blur sm:px-8">
      <form className="relative max-w-md flex-1" role="search" onSubmit={(e) => { e.preventDefault(); router.push(`${searchHref}?q=${encodeURIComponent(query)}`); }}>
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <label htmlFor="global-search" className="sr-only">Search</label>
        <input id="global-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={searchPlaceholder}
          className="w-full rounded-lg border border-line bg-canvas py-2 pr-3 pl-9 text-sm outline-none focus:border-brand-600 focus:bg-surface" />
      </form>
      <div className="ml-auto flex items-center gap-5">
        <Link href={alertsHref} className="relative rounded-lg p-1.5 text-gray-600 hover:bg-canvas" aria-label={`${alerts} items need attention`}>
          <Bell className="size-5" aria-hidden />
          {alerts > 0 && <span className="absolute -top-0.5 -right-0.5 grid size-4 place-items-center rounded-full bg-red-600 text-[10px] font-semibold text-white">{alerts}</span>}
        </Link>
        <div className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-full bg-brand-700 text-xs font-semibold text-white">{initials}</span>
          <div className="hidden leading-tight sm:block">
            <p className="text-sm font-semibold">{user ?? "Signing in…"}</p>
            <p className="text-xs text-muted">{subtitle}</p>
          </div>
          <form method="post" action="/auth/logout">
            <input type="hidden" name="csrf" value={token} />
            <button type="submit" className="rounded-md p-1.5 text-muted hover:bg-canvas" aria-label="Sign out"><LogOut className="size-4" aria-hidden /></button>
          </form>
        </div>
      </div>
    </header>
  );
}

/** Shown when the signed-in identity has no role in this portal (e.g. a staff account on the customer portal). */
export function NoAccess({ portal, message }: { portal: string; message: string }) {
  const [token, setToken] = useState("");
  useEffect(() => setToken(csrf()), []);
  return (
    <main className="grid min-h-screen flex-1 place-items-center px-4">
      <div role="alert" className="max-w-md rounded-xl border border-line bg-surface p-6 text-center">
        <ShieldCheck className="mx-auto size-8 text-brand-700" aria-hidden />
        <h1 className="mt-3 text-lg font-semibold">No access to the {portal}</h1>
        <p className="mt-2 text-sm text-muted">{message}</p>
        <p className="mt-2 text-sm text-muted">Sign out, then sign in with an account that belongs to this portal.</p>
        <form method="post" action="/auth/logout" className="mt-4">
          <input type="hidden" name="csrf" value={token} />
          <button type="submit" className="rounded-lg bg-brand-700 px-4 py-2 text-sm font-medium text-white hover:bg-brand-800">Sign out</button>
        </form>
      </div>
    </main>
  );
}
