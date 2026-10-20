import { connection, type NextRequest } from "next/server";
import { logoutHandler } from "@assureops/ui/server/oidc";
import { portal } from "@/lib/portal";

export async function POST(request: NextRequest) {
  await connection(); // request-time only: OIDC settings are never read while building
  return logoutHandler(portal())(request);
}
