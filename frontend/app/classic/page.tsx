import type { Metadata } from "next";
import { RequireAuth } from "@/components/require-auth";
import { Shell } from "@/components/shell";

export const metadata: Metadata = { title: "Classic — Career Guidance AI", robots: { index: false } };

/**
 * The classic tabbed app shell (previously the root page). Kept reachable
 * for users who prefer it; /dashboard is the signed-in home.
 */
export default function Page() {
  return (
    <RequireAuth>
      <Shell />
    </RequireAuth>
  );
}
