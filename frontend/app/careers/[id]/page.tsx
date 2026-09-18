import fs from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { CareerDetailView } from "@/components/career-detail-view";

/**
 * Career detail (`/careers/15-1199.08`).
 *
 * The page body is client-rendered (it needs the session cookie), but the
 * route itself is statically generated for all 974 catalogue ids so that the
 * offline/CI export contains a shell for every career the app links to. When
 * the catalogue file is not next to the app (standalone Docker build) the list
 * is empty and the route is simply absent from the export.
 */
export const dynamicParams = false;

function catalogueIds(): string[] {
  const candidates = [
    path.join(process.cwd(), "..", "data", "catalog", "occupations.json"),
    path.join(process.cwd(), "data", "catalog", "occupations.json"),
  ];
  for (const file of candidates) {
    try {
      const rows = JSON.parse(fs.readFileSync(file, "utf8")) as { id?: string }[];
      const ids = rows.map((row) => row.id).filter((id): id is string => Boolean(id));
      if (ids.length > 0) return ids;
    } catch {
      /* try the next location */
    }
  }
  return [];
}

export async function generateStaticParams() {
  return catalogueIds().map((id) => ({ id }));
}

export const metadata: Metadata = {
  title: "Career — Career Guidance AI",
  robots: { index: false },
};

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <AppPage>
      <CareerDetailView careerId={decodeURIComponent(id)} />
    </AppPage>
  );
}
