import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { PlanView } from "@/components/plan-view";

export const metadata: Metadata = { title: "Plan — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <PlanView />
    </AppPage>
  );
}
