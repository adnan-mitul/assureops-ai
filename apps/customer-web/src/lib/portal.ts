import "server-only";
import type { PortalConfig } from "@assureops/ui/server/oidc";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`missing server setting ${name}`);
  return value;
}

export function portal(): PortalConfig {
  return {
    issuer: required("OIDC_ISSUER"),
    clientId: required("OIDC_CLIENT_ID"),
    clientSecret: required("OIDC_CLIENT_SECRET"),
    origin: required("APP_ORIGIN"),
    apiUrl: required("ASSUREOPS_API_URL"),
    allowedPrefixes: ["v1/"],
    deniedPrefixes: ["v1/staff", "v1/integration", "v1/runtime"],
  };
}
