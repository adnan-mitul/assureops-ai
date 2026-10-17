import type { NextRequest } from "next/server";
import { logoutHandler } from "@assureops/ui/server/oidc";
import { portal } from "@/lib/portal";

export async function POST(request: NextRequest) {
  return logoutHandler(portal())(request);
}
