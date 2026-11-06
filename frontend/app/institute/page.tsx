import type { Metadata } from "next";
import { InstituteView } from "@/components/institute-view";
import { AppPage } from "@/components/app-page";

export const metadata: Metadata = { title: "Institute — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <InstituteView />
    </AppPage>
  );
}
