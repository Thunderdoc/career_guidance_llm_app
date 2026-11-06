"use client";

/**
 * /offline (Phase 8): the in-app offline page, localised EN/TA/HI.
 *
 * Two different offline surfaces exist on purpose:
 * - this React page is what a *connected* visitor (or a crawler, or the
 *   app router) reaches at /offline;
 * - `public/sw-offline.html` is the dependency-free static file the
 *   service worker precaches and serves when a navigation fails offline
 *   — it must work even if the JS bundle itself cannot load, so it is
 *   not this component. (It cannot live at public/offline.html: the
 *   static export emits this route to out/offline.html and overwrites
 *   the public file of the same name — verified in the Phase 8 build.)
 *   Their wording is kept in sync by hand.
 */
import Link from "next/link";
import { useI18n } from "@/lib/i18n";

export function OfflineView() {
  const { t } = useI18n();
  return (
    <main className="mx-auto grid min-h-dvh w-full max-w-xl place-items-center px-5 py-16">
      <div className="text-center">
        <h1 className="font-serif text-3xl">{t("p8_offline_title")}</h1>
        <p className="mt-3 text-sm leading-relaxed text-fg-2">{t("p8_offline_body")}</p>
        <Link
          href="/"
          className="mt-6 inline-block rounded-xl bg-white px-5 py-3 text-sm font-medium text-black hover:bg-white/90"
        >
          {t("p8_offline_retry")}
        </Link>
      </div>
    </main>
  );
}
