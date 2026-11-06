"use client";

/** /explore (Phase 1): careers, compare, job-fit, discover and transitions
 *  consolidated into one tabbed surface, reusing the existing views. */
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import dynamic from "next/dynamic";
import { Tabs } from "./ui/tabs";

// Each tab is code-split: the surface stays inside the 245 kB first-load
// budget (C8) and a tab's view loads only when the tab is opened.
const CareersView = dynamic(() => import("./careers-view").then((m) => m.CareersView));
const CompareView = dynamic(() => import("./compare-view").then((m) => m.CompareView));
const DiscoverView = dynamic(() => import("./discover-view").then((m) => m.DiscoverView));
const JobFitView = dynamic(() => import("./jobfit-view").then((m) => m.JobFitView));
const TransitionsView = dynamic(() => import("./transitions-view").then((m) => m.TransitionsView));

const TABS = [
  { id: "careers", label: "Careers" },
  { id: "compare", label: "Compare" },
  { id: "jobfit", label: "Job fit" },
  { id: "discover", label: "Discover" },
  { id: "transitions", label: "Transitions" },
];

export function ExploreView() {
  const params = useSearchParams();
  const initial = TABS.some((t) => t.id === params.get("tab")) ? (params.get("tab") as string) : "careers";
  const [tab, setTab] = useState(initial);
  return (
    <div>
      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      <div className="mt-6">
        {tab === "careers" && <CareersView />}
        {tab === "compare" && <CompareView />}
        {tab === "jobfit" && <JobFitView />}
        {tab === "discover" && <DiscoverView />}
        {tab === "transitions" && <TransitionsView />}
      </div>
    </div>
  );
}
