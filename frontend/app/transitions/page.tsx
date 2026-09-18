import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { TransitionsView } from "@/components/transitions-view";

export const metadata: Metadata = { title: "Career transitions — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <TransitionsView />
    </AppPage>
  );
}
