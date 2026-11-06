import type { Metadata } from "next";
import { MethodologyView } from "@/components/methodology-view";

export const metadata: Metadata = {
  title: "Methodology — Career Guidance AI",
  description:
    "How the career matcher and India Reality Score work, the data sources behind them, and their known limits. Guidance, not a guarantee of employment.",
};

export default function Page() {
  return <MethodologyView />;
}
