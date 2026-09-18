import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { RecommendView } from "@/components/recommend-view";

export const metadata: Metadata = { title: "Recommendations — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <RecommendView />
    </AppPage>
  );
}
