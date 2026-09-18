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
  Languages,
  LogIn,
  LogOut,
  ShieldCheck,
  Sparkles,
  Target,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { LOCALES, useI18n, type Key } from "@/lib/i18n";
import { useAuth } from "@/lib/auth-context";
import { AuthDialog } from "./auth-dialog";
import { AdminView } from "./admin-view";
import { Dock, ScrollProgress, Spotlight } from "./motion";
import { RecommendView } from "./recommend-view";
import { HistoryView } from "./history-view";
import { AssessmentView } from "./assessment-view";
import { JobFitView } from "./jobfit-view";
import { AboutModal } from "./about-modal";

export type PageId = "recommend" | "assessment" | "jobfit" | "history" | "admin";

const NAV_DEF: { id: PageId; label: Key; icon: React.ReactNode; hint: Key }[] = [
  { id: "recommend", label: "nav_recommend", icon: <Compass size={18} />, hint: "nav_recommend_hint" },
  { id: "assessment", label: "nav_assessment", icon: <Target size={18} />, hint: "nav_assessment_hint" },
  { id: "jobfit", label: "nav_jobfit", icon: <Briefcase size={18} />, hint: "nav_jobfit_hint" },
  { id: "history", label: "nav_history", icon: <History size={18} />, hint: "nav_history_hint" },
];

export function Shell() {
  const [page, setPage] = useState<PageId>("recommend");
  const [collapsed, setCollapsed] = useState(false);
  const [about, setAbout] = useState(false);
  const [health, setHealth] = useState<{ ai_mode: boolean; occupations: number; version: string } | null>(null);
  const [interestsProfile, setInterestsProfile] = useState<Record<string, number> | null>(null);
  const [hollandCode, setHollandCode] = useState<string | null>(null);
  const { t, locale, setLocale } = useI18n();
  const { user, logout } = useAuth();
  const [signIn, setSignIn] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const NAV = [
    ...NAV_DEF,
    ...(user?.is_admin ? [{ id: "admin" as PageId, label: "nav_admin" as Key, icon: <ShieldCheck size={18} />, hint: "nav_admin_hint" as Key }] : []),
  ].map((n) => ({ ...n, label: t(n.label), hint: t(n.hint) }));

  useEffect(() => {
    const url = new URL(window.location.href);
    const a = url.searchParams.get("auth");
    if (a === "expired" || a === "disabled" || a === "cancelled") {
      setToast(t(`auth_${a}` as Key));
      url.searchParams.delete("auth");
      window.history.replaceState({}, "", url.toString());
      const id = setTimeout(() => setToast(null), 6000);
      return () => clearTimeout(id);
    }
  }, [t]);

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
                <div className="text-sm font-semibold leading-tight">{t("app_name")}</div>
                <div className="text-[11px] text-fg-3">{health ? `${t("careers_count", { n: health.occupations })} · v${health.version}` : t("connecting")}</div>
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
                <span className="font-medium">{health?.ai_mode ? t("ai_mode") : t("offline_mode")}</span>
              </div>
              <p className="mt-1 text-[11px] leading-snug text-fg-3">
                {health?.ai_mode ? t("ai_mode_desc") : t("offline_mode_desc")}
              </p>
              {hollandCode && (
                <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-accent/15 px-2 py-0.5 text-[11px] text-accent">
                  <Target size={11} /> {t("interests_label")}: {hollandCode}
                </div>
              )}
            </div>
          )}
          {user ? (
            <div className={cn("mb-2 flex items-center gap-2 rounded-[var(--radius-md)] bg-bg-3 p-2", collapsed && "justify-center")}>
              <Avatar user={user} />
              {!collapsed && (
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-medium">{user.name || user.email}</div>
                  <div className="truncate text-[10px] text-fg-3">{user.is_admin ? "admin" : user.email}</div>
                </div>
              )}
              <button onClick={() => logout().then(() => setPage("recommend"))} title={t("sign_out")} aria-label={t("sign_out")} className="rounded-[var(--radius-sm)] p-1.5 text-fg-3 hover:bg-bg-4 hover:text-fg">
                <LogOut size={14} />
              </button>
            </div>
          ) : (
            <button
              onClick={() => (window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`)}
              className={cn("mb-2 flex w-full items-center gap-2 rounded-[var(--radius-md)] bg-accent/10 px-3 py-2 text-xs font-medium text-accent ring-1 ring-accent/20 transition hover:bg-accent/15", collapsed && "justify-center px-0")}
              title={t("sign_in")}
            >
              <LogIn size={14} /> {!collapsed && t("sign_in")}
            </button>
          )}
          <div className={cn("flex items-center gap-1", collapsed ? "flex-col" : "justify-between")}>
            <button onClick={() => setAbout(true)} className="rounded-[var(--radius-sm)] p-2 text-fg-3 transition hover:bg-bg-3 hover:text-fg" aria-label={t("about")}>
              <Info size={16} />
            </button>
            <label className="relative flex items-center gap-1 rounded-[var(--radius-sm)] p-2 text-fg-3 transition hover:bg-bg-3 hover:text-fg" title={t("language")}>
              <Languages size={16} />
              <select
                aria-label={t("language")}
                value={locale}
                onChange={(e) => setLocale(e.target.value as typeof locale)}
                className={cn("bg-transparent text-xs text-fg-2 focus:outline-none", collapsed && "absolute inset-0 opacity-0")}
              >
                {LOCALES.map((l) => (
                  <option key={l.id} value={l.id} className="bg-bg-3 text-fg">
                    {l.native}
                  </option>
                ))}
              </select>
            </label>
            <button onClick={toggle} className="rounded-[var(--radius-sm)] p-2 text-fg-3 transition hover:bg-bg-3 hover:text-fg" aria-label={collapsed ? t("expand_sidebar") : t("collapse_sidebar")}>
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
            {page === "admin" && <AdminView />}
          </motion.div>
        </AnimatePresence>
      </main>

      {/* Mobile / universal dock */}
      <Dock
        items={[
          ...NAV.map((n) => ({ id: n.id, label: n.label, icon: n.icon })),
          { id: "about", label: t("about"), icon: <BarChart3 size={18} /> },
          user ? { id: "logout", label: t("sign_out"), icon: <LogOut size={18} /> } : { id: "login", label: t("sign_in"), icon: <LogIn size={18} /> },
        ]}
        active={page}
        onSelect={(id) => {
          if (id === "about") setAbout(true);
          else if (id === "login") window.location.href = "/login";
          else if (id === "logout") logout().then(() => setPage("recommend"));
          else setPage(id as PageId);
        }}
      />

      <AboutModal open={about} onClose={() => setAbout(false)} />
      <AuthDialog open={signIn} onClose={() => setSignIn(false)} />
      <AnimatePresence>
        {toast && (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 20 }} className="fixed bottom-24 left-1/2 z-50 -translate-x-1/2 rounded-full bg-panel px-4 py-2 text-xs text-fg shadow-[var(--shadow-lg)] ring-1 ring-white/10">
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Avatar({ user }: { user: { name: string; email: string; picture: string } }) {
  const initial = (user.name || user.email).trim()[0]?.toUpperCase() ?? "?";
  return user.picture ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={user.picture} alt="" className="h-7 w-7 shrink-0 rounded-full ring-1 ring-white/10" referrerPolicy="no-referrer" />
  ) : (
    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-accent/20 text-xs font-semibold text-accent ring-1 ring-accent/30">{initial}</span>
  );
}
