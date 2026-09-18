"use client";

import { useEffect } from "react";

/**
 * Registers the service worker (`public/sw.js`) once, in production only.
 * The worker caches the app shell and the icon/font set; it deliberately never
 * caches `/api/*` responses because those carry per-account data.
 */
export function PwaRegister() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;
    const timer = window.setTimeout(() => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* offline support is a bonus, never a blocker */
      });
    }, 1_200);
    return () => window.clearTimeout(timer);
  }, []);
  return null;
}
