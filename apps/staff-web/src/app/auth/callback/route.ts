import type { NextRequest } from "next/server";
import { callbackHandler } from "@assureops/ui/server/oidc";
import { portal } from "@/lib/portal";

export async function GET(request: NextRequest) {
  return callbackHandler(portal())(request);
}
