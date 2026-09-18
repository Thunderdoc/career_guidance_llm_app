import type { Metadata } from "next";
import { AppPage } from "@/components/app-page";
import { InterviewView } from "@/components/interview-view";

export const metadata: Metadata = { title: "Interview prep — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return (
    <AppPage>
      <InterviewView />
    </AppPage>
  );
}
