import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { JobFitView } from "@/components/jobfit-view";

export const metadata: Metadata = { title: "Job fit — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <JobFitView />
    </AppPage>
  );
}
