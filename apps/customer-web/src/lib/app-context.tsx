"use client";

import { type ApiError, usePoll } from "@assureops/ui/client";
import { createContext, useContext, useState, type ReactNode } from "react";
import type { ApplicationSummary, Me } from "./types";

type Ctx = {
  me: Me | null;
  meError: ApiError | null;
  applications: ApplicationSummary[];
  applicationId: string | null;
  setApplicationId: (id: string) => void;
  canWrite: boolean;
  canReview: boolean;
};

const AppContext = createContext<Ctx>({ me: null, meError: null, applications: [], applicationId: null, setApplicationId: () => {}, canWrite: false, canReview: false });

function remembered(): string | null {
  try {
    return localStorage.getItem("assureops.application");
  } catch {
    return null;
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const { data: me, error: meError } = usePoll<Me>("/v1/me", 60000);
  const { data: applications } = usePoll<ApplicationSummary[]>("/v1/applications", 15000);
  const [chosen, setChosen] = useState<string | null>(null);
  const list = applications ?? [];
  const preferred = chosen ?? remembered();
  const applicationId = list.find((a) => a.id === preferred)?.id ?? list[0]?.id ?? null;

  const setApplicationId = (id: string) => {
    setChosen(id);
    try {
      localStorage.setItem("assureops.application", id);
    } catch {}
  };

  return (
    <AppContext.Provider value={{
      me, meError, applications: list, applicationId, setApplicationId,
      canWrite: me?.role === "owner" || me?.role === "developer",
      canReview: me?.role === "owner" || me?.role === "reviewer",
    }}>
      {children}
    </AppContext.Provider>
  );
}

export const useApp = () => useContext(AppContext);
