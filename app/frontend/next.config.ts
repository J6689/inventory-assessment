import type { NextConfig } from "next";

/** In dev, proxy /api to the FastAPI server so the frontend can run
 *  same-origin (no CORS juggling for the reviewer). Point the backend at
 *  :8000 with:  uvicorn app.main:app --port 8000  */
const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.BACKEND_URL ?? "http://127.0.0.1:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
