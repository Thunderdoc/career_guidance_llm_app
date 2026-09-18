import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { LearnView } from "@/components/learn-view";

export const metadata: Metadata = { title: "Learn — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <LearnView />
    </AppPage>
  );
}
