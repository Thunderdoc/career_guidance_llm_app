import type { Metadata } from "next";
import { PublicProfileView } from "@/components/public-profile-view";

export const metadata: Metadata = { title: "Verified skills — Career Guidance AI", robots: { index: false } };

/**
 * Static-export pattern (same as /report/[runId]): handles are unbounded,
 * so the export build emits one placeholder page ("_") and
 * backend/main.py's SPA fallback serves it for every /p/<handle>;
 * PublicProfileView then reads the real handle from the URL.
 */
export function generateStaticParams() {
  return [{ handle: "_" }];
}

export const dynamicParams = false;

export default async function Page({ params }: { params: Promise<{ handle: string }> }) {
  const { handle } = await params;
  return <PublicProfileView handle={handle} />;
}
