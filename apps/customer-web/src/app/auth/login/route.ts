import { connection, type NextRequest } from "next/server";
import { loginHandler } from "@assureops/ui/server/oidc";
import { portal } from "@/lib/portal";

export async function GET(request: NextRequest) {
  await connection(); // request-time only: OIDC settings are never read while building
  return loginHandler(portal())(request);
}
