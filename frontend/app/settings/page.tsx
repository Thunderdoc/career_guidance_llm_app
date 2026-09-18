import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { SettingsView } from "@/components/settings-view";

export const metadata: Metadata = { title: "Settings — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <SettingsView />
    </AppPage>
  );
}
