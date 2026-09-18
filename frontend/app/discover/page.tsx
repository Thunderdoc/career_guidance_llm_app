import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { DiscoverView } from "@/components/discover-view";

export const metadata: Metadata = { title: "Interest assessment — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <DiscoverView />
    </AppPage>
  );
}
