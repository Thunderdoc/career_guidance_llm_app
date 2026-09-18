import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { OnboardingWizard } from "@/components/onboarding-wizard";

export const metadata: Metadata = { title: "Get started — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <OnboardingWizard />
    </AppPage>
  );
}
