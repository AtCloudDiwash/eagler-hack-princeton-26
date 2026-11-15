import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

const nextConfig = (phase: string): NextConfig => ({
  // Keep production builds from replacing chunks used by a running dev server.
  distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next",
  // Self-contained server bundle for the Docker image (frontend/Dockerfile).
  output: "standalone",
});

export default nextConfig;
