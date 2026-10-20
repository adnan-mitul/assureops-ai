"use client";

import { useUnread } from "@assureops/ui/inbox";
import { MobileNav, NoAccess, Sidebar, SkipLink, Topbar, type NavItem } from "@assureops/ui/shell";
import { Activity, Boxes, Building2, ClipboardCheck, FileBadge, FileText, FolderKanban, GitBranch, House, Settings, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { AppProvider, useApp } from "@/lib/app-context";

const NAV: NavItem[] = [
  { href: "/overview", label: "Dashboard", icon: House },
  { href: "/applications", label: "Applications", icon: Boxes },
  { href: "/assessments", label: "Assessments", icon: ClipboardCheck },
  { href: "/findings", label: "Findings", icon: TriangleAlert },
  { href: "/evidence", label: "Evidence", icon: FileBadge },
  { href: "/releases", label: "Releases", icon: GitBranch },
  { href: "/monitoring", label: "Runtime Incidents", icon: Activity },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/cases", label: "Assessment Cases", icon: FolderKanban },
  { href: "/settings", label: "Settings", icon: Settings },
];

function Frame({ children }: { children: ReactNode }) {
  const { me, meError, applications, applicationId, setApplicationId } = useApp();
  const unread = useUnread(me ? "/v1/notifications" : "");

  if (meError?.status === 403) return <NoAccess portal="customer portal" message={meError.message} />;

  const org = (
    <div className="mt-6 border-t border-line pt-4">
      <p className="px-3 pb-2 text-xs font-medium text-muted">Current Organization</p>
      <div className="mx-1 flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm">
        <Building2 className="size-4 text-muted" aria-hidden />
        {me?.workspace_id ?? "…"}
      </div>
      {applications.length > 1 && (
        <label className="mx-1 mt-3 block text-xs text-muted">Application
          <select value={applicationId ?? ""} onChange={(e) => setApplicationId(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink">
            {applications.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </label>
      )}
    </div>
  );

  return (
    <>
      <SkipLink />
      <Sidebar portal="Customer Portal" items={NAV} footer={org} home="/overview" />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar user={me?.display_name ?? null} subtitle={me ? `${me.role} · ${me.workspace_id}` : "Customer portal"} alerts={unread} alertsHref="/notifications" searchHref="/findings" />
        <MobileNav items={NAV} />
        <main id="main" tabIndex={-1} className="flex-1 px-4 py-6 outline-none sm:px-8">{children}</main>
      </div>
    </>
  );
}

export function CustomerShell({ children }: { children: ReactNode }) {
  return (
    <AppProvider>
      <Frame>{children}</Frame>
    </AppProvider>
  );
}
