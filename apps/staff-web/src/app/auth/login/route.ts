import type { NextRequest } from "next/server";
import { loginHandler } from "@assureops/ui/server/oidc";
import { portal } from "@/lib/portal";

export async function GET(request: NextRequest) {
  return loginHandler(portal())(request);
}
