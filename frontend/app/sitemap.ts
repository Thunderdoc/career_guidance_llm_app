import type { MetadataRoute } from "next";

/**
 * Sitemap (Phase 6 SEO): the public, indexable surfaces only.
 * Account/admin/API routes are excluded here and disallowed in robots.ts.
 * Career detail pages are statically generated for all 974 catalogue ids;
 * they are reachable from /careers, which is the indexed entry point.
 */
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

export const dynamic = "force-static";

export default function sitemap(): MetadataRoute.Sitemap {
  const routes = [
    "",
    "/start",
    "/explore",
    "/careers",
    "/methodology",
    "/privacy",
    "/terms",
    "/refund",
  ];
  return routes.map((route) => ({
    url: `${SITE_URL}${route}`,
    changeFrequency: route === "" ? "weekly" : "monthly",
    priority: route === "" ? 1 : 0.7,
  }));
}
