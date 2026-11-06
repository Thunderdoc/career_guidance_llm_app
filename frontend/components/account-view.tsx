"use client";

/** /account (Phase 1): history, billing and settings in one tabbed surface,
 *  reusing the existing views. */
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { BillingView } from "./billing-view";
import { HistoryView } from "./history-view";
import { SettingsView } from "./settings-view";
import { Tabs } from "./ui/tabs";

const TABS = [
  { id: "history", label: "History" },
  { id: "billing", label: "Billing" },
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
        {tab === "billing" && <BillingView />}
        {tab === "settings" && <SettingsView />}
      </div>
    </div>
  );
}
