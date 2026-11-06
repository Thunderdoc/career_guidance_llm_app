import type { Metadata } from "next";

import { StatusView } from "@/components/status-view";

export const metadata: Metadata = {
  title: "Status — Career Guidance AI",
  robots: { index: false },
};

/**
 * /status (Phase 10): live API liveness + readiness, checked from the
 * visitor's browser at view time (see components/status-view.tsx).
 */
export default function Page() {
  return <StatusView />;
}
