import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { CompareView } from "@/components/compare-view";

export const metadata: Metadata = { title: "Compare careers — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <CompareView />
    </AppPage>
  );
}
