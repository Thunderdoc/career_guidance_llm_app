import type { Metadata } from "next";
import { ReportView } from "@/components/report-view";

export const metadata: Metadata = { title: "Career Report — Career Guidance AI", robots: { index: false } };

/**
 * Static-export pattern: run ids are unbounded, so the export build emits
 * one placeholder page ("_") and backend/main.py's SPA fallback serves it
 * for every /report/<id>; ReportView then reads the real id from the URL.
 * In the dev/server build the segment resolves dynamically as usual.
 */
export function generateStaticParams() {
  return [{ runId: "_" }];
}

export const dynamicParams = false;

export default async function Page({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <ReportView runId={runId} />;
}
