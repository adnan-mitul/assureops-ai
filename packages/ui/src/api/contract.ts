// Generated API contract helpers. `schema.d.ts` is generated from the backend's OpenAPI document
// (scripts/export_openapi.py + npm run gen:api); CI fails when it is out of date.
import type { paths } from "./schema";

export type ApiPath = keyof paths;

type Operation<P extends ApiPath, M extends string> = M extends keyof paths[P] ? NonNullable<paths[P][M]> : never;

/** JSON request body the backend accepts for this path and method. */
export type RequestBody<P extends ApiPath, M extends "post" | "put"> =
  Operation<P, M> extends { requestBody?: { content: { "application/json": infer B } } } ? B : never;

/** Fill a typed path template; a path that is not in the API contract does not compile. */
export function pathFor<P extends ApiPath>(template: P, params: Record<string, string> = {}): string {
  return (template as string).replace(/\{(\w+)\}/g, (_, key: string) => encodeURIComponent(params[key] ?? ""));
}
