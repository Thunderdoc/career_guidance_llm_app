import type { Metadata } from "next";
import { OfflineView } from "@/components/offline-view";

export const metadata: Metadata = { title: "Offline — Career Guidance AI", robots: { index: false } };

/**
 * /offline (Phase 8): localised offline page. The service worker's
 * offline fallback is the separate dependency-free
 * `public/sw-offline.html` (it must render even when the JS bundle
 * cannot load) — see components/offline-view.tsx for how the two are
 * kept in sync, and why the fallback is not at public/offline.html.
 */
export default function Page() {
  return <OfflineView />;
}
