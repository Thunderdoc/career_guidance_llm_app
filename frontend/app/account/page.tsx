import type { Metadata } from "next";
import { Suspense } from "react";
import { AccountView } from "@/components/account-view";
import { AppPage } from "@/components/app-page";

export const metadata: Metadata = { title: "Account — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <Suspense fallback={null}>
        <AccountView />
      </Suspense>
    </AppPage>
  );
}
