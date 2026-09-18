import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { PathwayView } from "@/components/pathway-view";

export const metadata: Metadata = { title: "Pathway check — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <PathwayView />
    </AppPage>
  );
}
