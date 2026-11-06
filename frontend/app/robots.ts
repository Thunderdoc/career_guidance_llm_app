import type { MetadataRoute } from "next";

/** Robots (Phase 6 SEO): public pages open, private surfaces disallowed. */
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

export const dynamic = "force-static";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/admin", "/account", "/api", "/dashboard", "/institute", "/p/"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
