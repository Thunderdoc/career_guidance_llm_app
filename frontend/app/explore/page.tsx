import type { Metadata } from "next";
import { Suspense } from "react";
import { AppPage } from "@/components/app-page";
import { ExploreView } from "@/components/explore-view";

export const metadata: Metadata = { title: "Explore — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <Suspense fallback={null}>
        <ExploreView />
      </Suspense>
    </AppPage>
  );
}
