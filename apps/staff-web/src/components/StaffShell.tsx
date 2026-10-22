"use client";

import { useUnread } from "@assureops/ui/inbox";
import { MobileNav, NoAccess, Sidebar, SkipLink, Topbar, type NavItem } from "@assureops/ui/shell";
import { Activity, ClipboardCheck, Inbox, Landmark, Server, UserCog } from "lucide-react";
import type { ReactNode } from "react";
import { ROLE_LABEL, StaffProvider, useStaff } from "@/lib/staff-context";

const NAV: NavItem[] = [
  { href: "/work-queue", label: "Work queue", icon: Inbox },
  { href: "/review-queue", label: "Review queue", icon: ClipboardCheck },
  { href: "/incidents", label: "Incidents", icon: Activity },
  { href: "/operations", label: "Operations", icon: Server },
  { href: "/governance", label: "Governance", icon: Landmark },
];

const ADMIN: NavItem = { href: "/admin", label: "Administration", icon: UserCog };

function Frame({ children }: { children: ReactNode }) {
  const { me, meError, hasRole } = useStaff();
  const unread = useUnread(me ? "/v1/staff/notifications" : "");
  const nav = hasRole("admin", "case_manager") ? [...NAV, ADMIN] : NAV;
  if (meError?.status === 403) return <NoAccess portal="staff portal" message={meError.message} />;
  const subtitle = me ? (me.roles.length ? me.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ") : "No staff roles") : "Staff portal";

  const footer = (
    <div className="mt-6 border-t border-line pt-4">
      <p className="px-3 text-xs leading-relaxed text-muted">
        Customer content is visible only through cases assigned to you. Every read is audited.
      </p>
    </div>
  );

  return (
    <>
      <SkipLink />
      <Sidebar portal="Staff Portal" items={nav} footer={footer} home="/work-queue" />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar user={me?.display_name ?? null} subtitle={subtitle} alerts={unread} alertsHref="/notifications" searchHref="/work-queue" />
        <MobileNav items={nav} />
        <main id="main" tabIndex={-1} className="flex-1 px-4 py-6 outline-none sm:px-8">{children}</main>
      </div>
    </>
  );
}

export function StaffShell({ children }: { children: ReactNode }) {
  return (
    <StaffProvider>
      <Frame>{children}</Frame>
    </StaffProvider>
  );
}
