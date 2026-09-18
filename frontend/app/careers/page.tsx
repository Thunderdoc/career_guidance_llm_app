import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { CareersView } from "@/components/careers-view";

export const metadata: Metadata = { title: "Careers — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <CareersView />
    </AppPage>
  );
}
