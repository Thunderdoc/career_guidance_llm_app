import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { HistoryView } from "@/components/history-view";

export const metadata: Metadata = { title: "History — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <HistoryView />
    </AppPage>
  );
}
