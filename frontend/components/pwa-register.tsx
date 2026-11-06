"use client";

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { Toast } from "./ui/toast";

/**
 * Registers the service worker (`public/sw.js`) once, in production only,
 * and surfaces its lifecycle through the UI kit's Toast (Phase 8):
 *
 * - first activation → a transient "App ready" toast;
 * - an updated worker reaching `installed` while an older one still
 *   controls the page → a sticky "Update available" toast whose Reload
 *   action posts SKIP_WAITING to the waiting worker; the resulting
 *   `controllerchange` reloads the page exactly once onto the new shell.
 *
 * The worker caches the app shell and static assets only; it deliberately
 * never caches `/api/*` responses because those carry per-account data.
 * CSP (report-only, Phase 6): the worker script is same-origin `/sw.js`,
 * covered by `script-src 'self'` — no policy change was needed; see
 * docs/SECURITY.md.
 */
export function PwaRegister() {
  const { t } = useI18n();
  const [toast, setToast] = useState<"ready" | "update" | null>(null);
  const waitingRef = useRef<ServiceWorker | null>(null);
  const reloadingRef = useRef(false);

  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;
    let cancelled = false;

    const onControllerChange = () => {
      if (!waitingRef.current || reloadingRef.current) return;
      reloadingRef.current = true;
      window.location.reload();
    };
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);

    const timer = window.setTimeout(() => {
      navigator.serviceWorker
        .register("/sw.js")
        .then((registration) => {
          if (cancelled) return;
          if (registration.waiting && navigator.serviceWorker.controller) {
            waitingRef.current = registration.waiting;
            setToast("update");
          }
          registration.addEventListener("updatefound", () => {
            const installing = registration.installing;
            if (!installing) return;
            installing.addEventListener("statechange", () => {
              if (installing.state !== "installed") return;
              if (navigator.serviceWorker.controller) {
                waitingRef.current = registration.waiting ?? installing;
                setToast("update");
              } else {
                setToast("ready");
              }
            });
          });
        })
        .catch(() => {
          /* offline support is a bonus, never a blocker */
        });
    }, 1_200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
    };
  }, []);

  if (toast === "update") {
    return (
      <Toast
        sticky
        message={t("p8_update_available")}
        action={{
          label: t("p8_reload"),
          onClick: () => waitingRef.current?.postMessage({ type: "SKIP_WAITING" }),
        }}
      />
    );
  }
  if (toast === "ready") {
    return <Toast message={t("p8_app_ready")} onDone={() => setToast(null)} />;
  }
  return null;
}
