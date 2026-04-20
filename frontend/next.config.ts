import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin workspace root to this directory so Turbopack ignores any
  // stray lockfile higher up in $HOME.
  turbopack: {
    root: path.resolve(__dirname),
  },
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
