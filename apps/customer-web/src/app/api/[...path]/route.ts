import type { NextRequest } from "next/server";
import { proxyHandler } from "@assureops/ui/server/oidc";
import { portal } from "@/lib/portal";

type Context = { params: Promise<{ path: string[] }> };

const handle = (request: NextRequest, context: Context) => proxyHandler(portal())(request, context);

export const GET = handle;
export const POST = handle;
export const DELETE = handle;
