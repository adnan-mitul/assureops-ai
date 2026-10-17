"use client";

import { type ApiError, usePoll } from "@assureops/ui/client";
import { createContext, useContext, type ReactNode } from "react";
import type { Me, QueueItem } from "./types";

type Ctx = {
  me: Me | null;
  meError: ApiError | null;
  roles: string[];
  hasRole: (...roles: string[]) => boolean;
  /** Work-queue items with at least one blocker (topbar alert count). */
  blocked: number;
};

const StaffContext = createContext<Ctx>({ me: null, meError: null, roles: [], hasRole: () => false, blocked: 0 });

export function StaffProvider({ children }: { children: ReactNode }) {
  const { data: me, error: meError } = usePoll<Me>("/v1/staff/me", 60000);
  const { data: queue } = usePoll<QueueItem[]>("/v1/staff/work-queue", 20000);
  const roles = me?.roles ?? [];
  const value: Ctx = {
    me,
    meError,
    roles,
    hasRole: (...wanted) => wanted.some((r) => roles.includes(r)),
    blocked: queue?.filter((q) => q.blockers > 0).length ?? 0,
  };
  return <StaffContext.Provider value={value}>{children}</StaffContext.Provider>;
}

export const useStaff = () => useContext(StaffContext);

export const ROLE_LABEL: Record<string, string> = {
  analyst: "Analyst",
  senior_reviewer: "Senior reviewer",
  case_manager: "Case manager",
  operator: "Operator",
};
