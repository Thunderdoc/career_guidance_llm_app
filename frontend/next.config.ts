import type { NextConfig } from "next";

const isExport = process.env.NEXT_EXPORT === "1";
const apiTarget = process.env.API_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: isExport ? "export" : undefined,
  trailingSlash: false,
  images: { unoptimized: true },
  allowedDevOrigins: ["*.e2b.app", "localhost", "127.0.0.1"],
  async rewrites() {
    if (isExport) return [];
    return [{ source: "/api/:path*", destination: `${apiTarget}/api/:path*` }];
  },
};

export default nextConfig;
