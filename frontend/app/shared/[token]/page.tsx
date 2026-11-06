import type { Metadata } from "next";
import { SharedReportView } from "@/components/shared-report-view";

export const metadata: Metadata = { title: "Shared Career Report — Career Guidance AI", robots: { index: false } };

/**
 * Static-export pattern (same as /report/[runId]): share tokens are
 * unbounded, so the export build emits one placeholder page ("_") and
 * backend/main.py's SPA fallback serves it for every /shared/<token>;
 * SharedReportView then reads the real token from the URL.
 */
export function generateStaticParams() {
  return [{ token: "_" }];
}

export const dynamicParams = false;

export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <SharedReportView token={token} />;
}
