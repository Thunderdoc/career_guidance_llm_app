import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { BillingView } from "@/components/billing-view";

export const metadata: Metadata = { title: "Billing — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <BillingView />
    </AppPage>
  );
}
