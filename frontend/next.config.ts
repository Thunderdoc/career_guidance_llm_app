import type { NextConfig } from "next";

const isExport = process.env.NEXT_EXPORT === "1";
const apiTarget = process.env.API_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: isExport ? "export" : undefined,
  trailingSlash: false,
  images: { unoptimized: true },
  allowedDevOrigins: ["*.e2b.app", "localhost", "127.0.0.1"],
  async redirects() {
    // Phase 1 route consolidation — see docs/ROUTES.md. Old routes keep
    // working by landing on their new surface. Static exports cannot emit
    // server redirects, so (like rewrites) this is dev/server-only; in the
    // export build the old pages themselves still serve.
    if (isExport) return [];
    return [
      { source: "/recommend", destination: "/start", permanent: false },
      { source: "/onboarding", destination: "/start", permanent: false },
      { source: "/discover", destination: "/explore?tab=discover", permanent: false },
      { source: "/careers", destination: "/explore?tab=careers", permanent: false },
      { source: "/compare", destination: "/explore?tab=compare", permanent: false },
      { source: "/jobfit", destination: "/explore?tab=jobfit", permanent: false },
      { source: "/transitions", destination: "/explore?tab=transitions", permanent: false },
      { source: "/history", destination: "/account?tab=history", permanent: false },
      { source: "/billing", destination: "/account?tab=billing", permanent: false },
      { source: "/settings", destination: "/account?tab=settings", permanent: false },
      { source: "/learn", destination: "/plan", permanent: false },
      { source: "/pathway", destination: "/plan", permanent: false },
    ];
  },
  async rewrites() {
    if (isExport) return [];
    return [{ source: "/api/:path*", destination: `${apiTarget}/api/:path*` }];
  },
};

export default nextConfig;
