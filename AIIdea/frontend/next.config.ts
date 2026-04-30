import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin Turbopack to this package so it doesn't walk up to the repo root
  // (the root has a package-lock.json for Playwright E2E and would otherwise
  // be chosen as the workspace root, breaking module resolution).
  turbopack: {
    root: import.meta.dirname,
  },
};

export default nextConfig;
