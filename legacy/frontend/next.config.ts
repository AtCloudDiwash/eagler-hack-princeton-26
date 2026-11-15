import type { NextConfig } from "next";

// Backend origin for the dev proxy. Browser code calls relative `/api/v1/...` URLs and
// Next.js forwards them to FastAPI, so no CORS setup or hard-coded host is needed in components.
const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${API_ORIGIN}/api/v1/:path*` },
      // Placeholder aerials, floor plans and listing photos served by FastAPI.
      { source: "/static/:path*", destination: `${API_ORIGIN}/static/:path*` },
      { source: "/health", destination: `${API_ORIGIN}/health` },
    ];
  },
};

export default nextConfig;
