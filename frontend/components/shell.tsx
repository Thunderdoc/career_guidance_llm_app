"use client";

import { AnimatePresence, motion } from "motion/react";
import {
  BarChart3,
  Briefcase,
  ChevronsLeft,
  ChevronsRight,
  Compass,
  History,
  Info,
  Sparkles,
  Target,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Dock, ScrollProgress, Spotlight } from "./motion";
import { RecommendView } from "./recommend-view";
import { HistoryView } from "./history-view";
import { AssessmentView } from "./assessment-view";
import { JobFitView } from "./jobfit-view";
import { AboutModal } from "./about-modal";

export type PageId = "recommend" | "assessment" | "jobfit" | "history";

const NAV: { id: PageId; label: string; icon: React.ReactNode; hint: string }[] = [
  { id: "recommend", label: "Recommend", icon: <Compass size={18} />, hint: "Profile → 5 careers" },
  { id: "assessment", label: "Interests", icon: <Target size={18} />, hint: "18-question RIASEC" },
  { id: "jobfit", label: "Job fit", icon: <Briefcase size={18} />, hint: "Paste a JD, see gaps" },
  { id: "history", label: "History", icon: <History size={18} />, hint: "Saved runs & stats" },
];

export function Shell() {
  const [page, setPage] = useState<PageId>("recommend");
  const [collapsed, setCollapsed] = useState(false);
  const [about, setAbout] = useState(false);
  const [health, setHealth] = useState<{ ai_mode: boolean; occupations: number; version: string } | null>(null);
  const [interestsProfile, setInterestsProfile] = useState<Record<string, number> | null>(null);
  const [hollandCode, setHollandCode] = useState<string | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    const saved = window.localStorage.getItem("cg.sidebar");
    if (saved === "collapsed") setCollapsed(true);
  }, []);

  const toggle = useCallback(() => {
    setCollapsed((c) => {
      window.localStorage.setItem("cg.sidebar", c ? "expanded" : "collapsed");
      return !c;
    });
  }, []);

  const onAssessed = (scores: Record<string, number>, code: string) => {
    setInterestsProfile(scores);
    setHollandCode(code);
    setPage("recommend");
  };

  return (
    <div className="relative flex min-h-dvh">
      <ScrollProgress />
      <Spotlight />
      <div className="spotlight left-[-10%] top-[-10%] h-[40rem] w-[40rem] bg-accent/40" />
      <div className="spotlight right-[-10%] top-[30%] h-[30rem] w-[30rem] bg-gold/30 [animation-delay:-9s]" />

      {/* Sidebar */}
      <motion.aside
        animate={{ width: collapsed ? "var(--sidebar-width-collapsed)" : "var(--sidebar-width-expanded)" }}
        transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
        className="sticky top-0 z-30 hidden h-dvh shrink-0 flex-col border-r border-white/5 bg-bg-2/80 backdrop-blur-md md:flex"
      >
        <div className={cn("flex items-center gap-3 px-3 py-4", collapsed && "justify-center px-0")}>
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius-md)] bg-accent/15 text-accent ring-1 ring-accent/30">
            <Sparkles size={18} />
          </div>
          <AnimatePresence initial={false}>
            {!collapsed && (
              <motion.div initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} transition={{ duration: 0.15 }}>
                <div className="text-sm font-semibold leading-tight">Career Guidance AI</div>
                <div className="text-[11px] text-fg-3">{health ? `${health.occupations} careers · v${health.version}` : "connecting…"}</div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <nav className="mt-2 flex flex-1 flex-col gap-1 px-2" aria-label="Sections">
          {NAV.map((n) => {
            const active = page === n.id;
            return (
              <button
                key={n.id}
                onClick={() => setPage(n.id)}
                aria-current={active ? "page" : undefined}
                title={collapsed ? n.label : undefined}
                className={cn(
                  "group relative flex items-center gap-3 rounded-[var(--radius-md)] px-3 py-2.5 text-left text-sm transition-colors",
                  active ? "text-fg" : "text-fg-2 hover:bg-bg-3 hover:text-fg",
                  collapsed && "justify-center px-0",
                )}
              >
                {active && (
                  <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-[var(--radius-md)] bg-bg-3 ring-1 ring-white/5" transition={{ type: "spring", stiffness: 350, damping: 30 }} />
                )}
                <span className={cn("relative z-10 shrink-0", active && "text-accent")}>{n.icon}</span>
                {!collapsed && (
                  <span className="relative z-10 flex flex-col">
                    <span className="font-medium">{n.label}</span>
                    <span className="text-[11px] text-fg-3">{n.hint}</span>
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="border-t border-white/5 p-2">
          {!collapsed && (
            <div className="mb-2 rounded-[var(--radius-md)] bg-bg-3 p-3">
              <div className="flex items-center gap-2 text-xs">
                <span className={cn("h-2 w-2 rounded-full", health?.ai_mode ? "bg-active status-pulse" : "bg-gold")} />
                <span className="font-medium">{health?.ai_mode ? "AI mode" : "Offline mode"}</span>
              </div>
              <p className="mt-1 text-[11px] leading-snug text-fg-3">
                {health?.ai_mode ? "LLM explanations grounded in O*NET." : "Semantic matching over 970+ O*NET occupations. Set OPENAI_API_KEY for AI explanations."}
              </p>
              {hollandCode && (
                <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-accent/15 px-2 py-0.5 text-[11px] text-accent">
                  <Target size={11} /> Interests: {hollandCode}
                </div>
              )}
            </div>
          )}
          <div className={cn("flex items-center gap-1", collapsed ? "flex-col" : "justify-between")}>
            <button onClick={() => setAbout(true)} className="rounded-[var(--radius-sm)] p-2 text-fg-3 transition hover:bg-bg-3 hover:text-fg" aria-label="About">
              <Info size={16} />
            </button>
            <button onClick={toggle} className="rounded-[var(--radius-sm)] p-2 text-fg-3 transition hover:bg-bg-3 hover:text-fg" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
              {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
            </button>
          </div>
        </div>
      </motion.aside>

      {/* Main */}
      <main className="relative z-10 min-w-0 flex-1 pb-28">
        <AnimatePresence mode="wait">
          <motion.div
            key={page}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            className="mx-auto w-full max-w-[880px] px-4 pt-6 sm:px-8 sm:pt-10"
          >
            {page === "recommend" && <RecommendView interestsProfile={interestsProfile} hollandCode={hollandCode} aiMode={!!health?.ai_mode} onGoAssess={() => setPage("assessment")} />}
            {page === "assessment" && <AssessmentView onDone={onAssessed} />}
            {page === "jobfit" && <JobFitView />}
            {page === "history" && <HistoryView />}
          </motion.div>
        </AnimatePresence>
      </main>

      {/* Mobile / universal dock */}
      <Dock
        items={[
          ...NAV.map((n) => ({ id: n.id, label: n.label, icon: n.icon })),
          { id: "about", label: "About", icon: <BarChart3 size={18} /> },
        ]}
        active={page}
        onSelect={(id) => (id === "about" ? setAbout(true) : setPage(id as PageId))}
      />

      <AboutModal open={about} onClose={() => setAbout(false)} />
    </div>
  );
}
