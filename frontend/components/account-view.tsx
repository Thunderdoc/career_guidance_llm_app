"use client";

/** /account (Phase 1): history, billing and settings in one tabbed surface,
 *  reusing the existing views. */
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { BillingView } from "./billing-view";
import { HistoryView } from "./history-view";
import { SettingsView } from "./settings-view";
import { Tabs } from "./ui/tabs";

// Phase 3: the verify tab is code-split so /account's first load stays
// inside the ≤245 kB budget; the chunk loads only when the tab is opened.
const VerifyView = dynamic(() => import("./verify-view").then((m) => m.VerifyView), {
  ssr: false,
});

// Phase 4: the institute tab is code-split for the same budget reason.
const InstituteView = dynamic(() => import("./institute-view").then((m) => m.InstituteView), {
  ssr: false,
});

// Phase 5: the privacy tab (age declaration + parental consent) is
// code-split for the same budget reason.
const ConsentView = dynamic(() => import("./consent-view").then((m) => m.ConsentView), {
  ssr: false,
});

const TABS = [
  { id: "history", label: "History" },
  { id: "verify", label: "Verify skills" },
  { id: "institute", label: "Institute" },
  { id: "billing", label: "Billing" },
  { id: "privacy", label: "Privacy" },
  { id: "settings", label: "Settings" },
];

export function AccountView() {
  const params = useSearchParams();
  const initial = TABS.some((t) => t.id === params.get("tab")) ? (params.get("tab") as string) : "history";
  const [tab, setTab] = useState(initial);
  return (
    <div>
      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      <div className="mt-6">
        {tab === "history" && <HistoryView />}
        {tab === "verify" && <VerifyView />}
        {tab === "institute" && <InstituteView />}
        {tab === "billing" && <BillingView />}
        {tab === "privacy" && <ConsentView />}
        {tab === "settings" && <SettingsView />}
      </div>
    </div>
  );
}
