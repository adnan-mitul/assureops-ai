import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Container builds (infra/portal/Dockerfile) emit a self-contained server; local dev and CI builds are unchanged.
  ...(process.env.NEXT_STANDALONE ? { output: "standalone" as const, outputFileTracingRoot: path.resolve(__dirname, "../..") } : {}),
  cacheComponents: true,
  partialPrefetching: true,
  transpilePackages: ["@assureops/ui"],
  async redirects() {
    return [{ source: "/", destination: "/overview", permanent: false }];
  },
  turbopack: {
    root: path.resolve(__dirname, "../.."),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
