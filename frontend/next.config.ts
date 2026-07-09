import type { NextConfig } from "next";

// Default points at `wrangler dev`'s local port (plan 2026-07-09-001, U8 —
// the Worker API replaces FastAPI as the frontend's backend). Production
// sets API_ORIGIN to the deployed Worker's URL (workers.dev or a custom
// domain). FastAPI (api/main.py) remains local-only build/validation
// tooling — point API_ORIGIN at :8000 only if you're deliberately testing
// against it.
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8787";

const nextConfig: NextConfig = {
  // Same-origin proxy (KTD2): the browser only ever calls /api/* on :3000;
  // Next forwards to the Worker. No CORS, no client-side API-origin env
  // plumbing, and the deploy story stays origin-stable.
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
