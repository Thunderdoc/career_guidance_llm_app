import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { ResumeView } from "@/components/resume-view";

export const metadata: Metadata = { title: "Résumé — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <ResumeView />
    </AppPage>
  );
}
