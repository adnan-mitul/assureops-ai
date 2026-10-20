import { connection, type NextRequest } from "next/server";
import { sessionInfoHandler } from "@assureops/ui/server/oidc";

export async function GET(request: NextRequest) {
  await connection(); // request-time only: OIDC settings are never read while building
  return sessionInfoHandler("customer-web")(request);
}
