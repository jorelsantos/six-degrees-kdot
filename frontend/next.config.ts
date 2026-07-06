import type { NextConfig } from "next";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Same-origin proxy (KTD2): the browser only ever calls /api/* on :3000;
  // Next forwards to the FastAPI engine. No CORS, no client-side API-origin
  // env plumbing, and the deploy story stays origin-stable.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
