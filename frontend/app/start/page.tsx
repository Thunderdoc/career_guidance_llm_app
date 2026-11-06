import type { Metadata } from "next";
import { StartWizard } from "@/components/start-wizard";

export const metadata: Metadata = { title: "Start — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return <StartWizard />;
}
