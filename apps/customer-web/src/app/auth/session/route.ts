import type { NextRequest } from "next/server";
import { sessionInfoHandler } from "@assureops/ui/server/oidc";

export async function GET(request: NextRequest) {
  return sessionInfoHandler("customer-web")(request);
}
