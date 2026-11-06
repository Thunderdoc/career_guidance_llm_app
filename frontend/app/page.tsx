/**
 * Public root: the landing page for anonymous visitors.
 *
 * This page is a server component on purpose: the landing copy is rendered
 * into the static HTML (search engines and no-JS visitors see the pitch).
 * Signed-in visitors are redirected by the <SignedInRedirect /> island.
 * The old tabbed app shell still lives at /classic.
 */
import { LandingView } from "@/components/landing-view";
import { SignedInRedirect } from "@/components/signed-in-redirect";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

/** JSON-LD (Phase 6 SEO): static organisation/website facts only. */
const JSON_LD = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      name: "Career Guidance AI",
      url: SITE_URL,
      description:
        "Skill-gap analysis and learning roadmaps for 974 O*NET occupations, with curated market data for India.",
    },
    {
      "@type": "WebSite",
      name: "Career Guidance AI",
      url: SITE_URL,
      inLanguage: ["en", "ta", "hi"],
    },
  ],
};

export default function Page() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }}
      />
      <SignedInRedirect />
      <LandingView />
    </>
  );
}
