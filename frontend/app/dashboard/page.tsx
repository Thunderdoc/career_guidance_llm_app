import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { DashboardView } from "@/components/dashboard-view";

export const metadata: Metadata = { title: "Dashboard — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <DashboardView />
    </AppPage>
  );
}
