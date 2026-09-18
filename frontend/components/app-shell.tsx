"use client";

/**
 * Routed application shell: sidebar navigation, locale switcher, XP chip,
 * announcements and the feedback widget.
 *
 * The admin link only renders for `user.is_admin` (the server also enforces it
 * on every /api/v1/admin/* route).
 */

import { AnimatePresence, motion } from "motion/react";
import {
  ArrowLeftRight,
  BarChart3,
  BookOpen,
  Briefcase,
  ChevronsLeft,
  ChevronsRight,
  Compass,
  FileText,
  History,
  LayoutDashboard,
  Languages,
  LogOut,
  MessageSquare,
  Mic,
  Search,
  Route,
  Settings,
  ShieldCheck,
  Sparkles,
  Target,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, gamification } from "@/lib/api";
import type { XpStatus } from "@/lib/types";
import { cn } from "@/lib/cn";
import { LOCALES, useI18n, type Key } from "@/lib/i18n";
import { useAuth } from "@/lib/auth-context";
import { useServerState } from "@/lib/use-server-state";
import { Modal, ScrollProgress, Spotlight } from "./motion";
import { Badge, Button } from "./ui";

type NavItem = { href: string; label: Key; icon: React.ReactNode };

const NAV: { group: Key; items: NavItem[] }[] = [
  {
    group: "nav_group_start",
    items: [
      { href: "/dashboard", label: "nav_dashboard", icon: <LayoutDashboard size={17} /> },
      { href: "/recommend", label: "nav_recommend", icon: <Compass size={17} /> },
      { href: "/pathway", label: "nav_pathway", icon: <Route size={17} /> },
      { href: "/discover", label: "nav_discover", icon: <Target size={17} /> },
    ],
  },
  {
    group: "nav_group_grow",
    items: [
      { href: "/plan", label: "nav_plan", icon: <Route size={17} /> },
      { href: "/learn", label: "nav_learn", icon: <BookOpen size={17} /> },
      { href: "/resume", label: "nav_resume", icon: <FileText size={17} /> },
      { href: "/jobfit", label: "nav_jobfit", icon: <Briefcase size={17} /> },
      { href: "/interview", label: "nav_interview", icon: <Mic size={17} /> },
    ],
  },
  {
    group: "nav_group_explore",
    items: [
      { href: "/careers", label: "nav_careers", icon: <Search size={17} /> },
      { href: "/compare", label: "nav_compare", icon: <BarChart3 size={17} /> },
      { href: "/transitions", label: "nav_transitions", icon: <ArrowLeftRight size={17} /> },
      { href: "/history", label: "nav_history", icon: <History size={17} /> },
    ],
  },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { t, locale, setLocale } = useI18n();
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const serverState = useServerState();
  const [collapsed, setCollapsed] = useState(false);
  const [xp, setXp] = useState<XpStatus | null>(null);
  const [announcements, setAnnouncements] = useState<
    { id: number; title: string; body: string; level: string; pinned: boolean }[]
  >([]);
  const [dismissed, setDismissed] = useState<number[]>([]);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("cg.sidebar");
    if (saved === "collapsed") setCollapsed(true);
    const seen = JSON.parse(window.localStorage.getItem("cg.dismissed") ?? "[]") as number[];
    setDismissed(seen);
  }, []);

  useEffect(() => {
    gamification
      .status()
      .then(setXp)
      .catch(() => setXp(null));
    api
      .announcements()
      .then((r) => setAnnouncements(r.announcements ?? []))
      .catch(() => setAnnouncements([]));
  }, [pathname]);

  const toggle = useCallback(() => {
    setCollapsed((c) => {
      window.localStorage.setItem("cg.sidebar", c ? "expanded" : "collapsed");
      return !c;
    });
  }, []);

  const dismiss = (id: number) => {
    const next = [...dismissed, id];
    setDismissed(next);
    window.localStorage.setItem("cg.dismissed", JSON.stringify(next));
  };

  const visible = announcements.filter((a) => !dismissed.includes(a.id));
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  return (
    <div className="relative flex min-h-dvh">
      <ScrollProgress />
      <Spotlight />
      <div className="spotlight left-[-10%] top-[-10%] h-[40rem] w-[40rem] bg-accent/40" />
      <div className="spotlight right-[-10%] top-[30%] h-[30rem] w-[30rem] bg-gold/30 [animation-delay:-9s]" />

      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-bg"
      >
        {t("skip_to_content")}
      </a>

      {/* Sidebar */}
      <motion.aside
        aria-label={t("app_name")}
        animate={{ width: collapsed ? "var(--sidebar-width-collapsed)" : "var(--sidebar-width-expanded)" }}
        transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
        className={cn(
          "sticky top-0 z-30 hidden h-dvh shrink-0 flex-col border-r border-white/5 bg-bg-2/80 backdrop-blur-md md:flex",
          mobileOpen && "hidden",
        )}
      >
        <Link href="/dashboard" className={cn("flex items-center gap-3 px-3 py-4", collapsed && "justify-center px-0")}>
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius-md)] bg-accent/15 text-accent ring-1 ring-accent/30">
            <Sparkles size={18} />
          </span>
          {!collapsed && (
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold leading-tight">{t("app_name")}</span>
              <span className="block text-[11px] text-fg-3">{t("app_tagline")}</span>
            </span>
          )}
        </Link>

        <nav className="mt-1 flex flex-1 flex-col gap-3 overflow-y-auto px-2 pb-4" aria-label={t("nav_sections")}>
          {NAV.map((group) => (
            <div key={group.group}>
              {!collapsed && (
                <p className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-fg-3">
                  {t(group.group)}
                </p>
              )}
              <div className="flex flex-col gap-0.5">
                {group.items.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={t(item.label)}
                    aria-current={isActive(item.href) ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm transition",
                      collapsed && "justify-center px-0",
                      isActive(item.href)
                        ? "bg-accent/12 text-accent ring-1 ring-accent/25"
                        : "text-fg-2 hover:bg-white/5 hover:text-fg",
                    )}
                  >
                    {item.icon}
                    {!collapsed && <span className="truncate">{t(item.label)}</span>}
                  </Link>
                ))}
              </div>
            </div>
          ))}
          {user?.is_admin && (
            <div>
              {!collapsed && (
                <p className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-fg-3">
                  {t("nav_group_admin")}
                </p>
              )}
              <Link
                href="/admin"
                title={t("nav_admin")}
                aria-current={isActive("/admin") ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm transition",
                  collapsed && "justify-center px-0",
                  isActive("/admin") ? "bg-gold/12 text-gold ring-1 ring-gold/25" : "text-fg-2 hover:bg-white/5 hover:text-fg",
                )}
              >
                <ShieldCheck size={17} />
                {!collapsed && <span className="truncate">{t("nav_admin")}</span>}
              </Link>
            </div>
          )}
        </nav>

        <div className="border-t border-white/5 p-2">
          <button
            onClick={() => setFeedbackOpen(true)}
            className={cn(
              "flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm text-fg-2 transition hover:bg-white/5 hover:text-fg",
              collapsed && "justify-center px-0",
            )}
            title={t("feedback_cta")}
          >
            <MessageSquare size={17} />
            {!collapsed && <span>{t("feedback_cta")}</span>}
          </button>
          <button
            onClick={toggle}
            className={cn(
              "flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-xs text-fg-3 transition hover:bg-white/5 hover:text-fg",
              collapsed && "justify-center px-0",
            )}
            aria-label={collapsed ? t("expand_sidebar") : t("collapse_sidebar")}
            title={collapsed ? t("expand_sidebar") : t("collapse_sidebar")}
          >
            {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
            {!collapsed && <span>{t("collapse_sidebar")}</span>}
          </button>
        </div>
      </motion.aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-white/5 bg-bg/85 px-4 py-2.5 backdrop-blur-md">
          <Link href="/dashboard" className="flex items-center gap-2 md:hidden">
            <Sparkles size={16} className="text-accent" />
            <span className="text-sm font-semibold">{t("app_name")}</span>
          </Link>
          <button
            className="ml-auto rounded-lg border border-white/10 px-2 py-1 text-xs text-fg-2 md:hidden"
            onClick={() => setMobileOpen((v) => !v)}
            aria-expanded={mobileOpen}
          >
            {t("menu")}
          </button>

          {xp && (
            <Link
              href="/dashboard#progress"
              className="hidden items-center gap-2 rounded-full border border-white/10 px-2.5 py-1 text-xs text-fg-2 sm:flex"
              title={t("xp_hint")}
            >
              <span className="text-accent">{xp.xp} XP</span>
              <span className="text-fg-3">·</span>
              <span>{t("level_label")} {xp.level}</span>
              <span className="text-fg-3">·</span>
              <span title={t("streak_hint")}>
                🔥 {xp.streak.current}
              </span>
            </Link>
          )}

          {user?.is_admin && (
            <Link href="/admin" className="hidden text-xs text-gold hover:underline sm:block">
              {t("nav_admin")}
            </Link>
          )}
          <Link href="/settings" className="rounded-lg p-1.5 text-fg-3 transition hover:bg-white/5 hover:text-fg" title={t("nav_settings")}>
            <Settings size={16} />
          </Link>
          <div className="relative">
            <label className="sr-only" htmlFor="locale">
              {t("language")}
            </label>
            <select
              id="locale"
              value={locale}
              onChange={(e) => setLocale(e.target.value as typeof locale)}
              className="appearance-none rounded-lg border border-white/10 bg-bg-3/60 py-1 pl-2 pr-6 text-xs text-fg-2"
            >
              {LOCALES.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.native}
                </option>
              ))}
            </select>
            <Languages size={12} className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-fg-3" />
          </div>
          <button
            onClick={() => void logout().then(() => window.location.replace("/login"))}
            className="rounded-lg p-1.5 text-fg-3 transition hover:bg-white/5 hover:text-fg"
            title={t("sign_out")}
            aria-label={t("sign_out")}
          >
            <LogOut size={16} />
          </button>
        </header>

        {serverState === "waking" && (
          <p role="status" aria-live="polite" className="border-b border-gold/20 bg-gold/10 px-4 py-1.5 text-xs text-gold">
            {t("waking_server")}
          </p>
        )}
        {serverState === "unreachable" && (
          <p role="alert" className="border-b border-danger/25 bg-danger/10 px-4 py-1.5 text-xs text-danger">
            {t("server_unreachable")}
          </p>
        )}

        {visible.length > 0 && (
          <div className="flex flex-col gap-1 border-b border-white/5 bg-bg-2/50 px-4 py-2">
            {visible.map((a) => (
              <div key={a.id} className="flex items-start gap-2 text-xs text-fg-2">
                <Badge tone={a.level === "warning" ? "gold" : a.level === "success" ? "ok" : "accent"}>
                  {a.pinned ? t("pinned") : t("notice")}
                </Badge>
                <span className="font-medium text-fg">{a.title}</span>
                <span className="flex-1">{a.body}</span>
                <button onClick={() => dismiss(a.id)} className="text-fg-3 hover:text-fg">
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        <AnimatePresence>
          {mobileOpen && (
            <motion.nav
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="flex flex-col gap-1 overflow-hidden border-b border-white/5 bg-bg-2/90 px-3 py-2 md:hidden"
              aria-label={t("nav_sections")}
            >
              {NAV.flatMap((g) => g.items).map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMobileOpen(false)}
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-2 py-2 text-sm",
                    isActive(item.href) ? "bg-accent/12 text-accent" : "text-fg-2",
                  )}
                >
                  {item.icon}
                  {t(item.label)}
                </Link>
              ))}
              {user?.is_admin && (
                <Link href="/admin" onClick={() => setMobileOpen(false)} className="flex items-center gap-2 rounded-lg px-2 py-2 text-sm text-gold">
                  <ShieldCheck size={17} /> {t("nav_admin")}
                </Link>
              )}
            </motion.nav>
          )}
        </AnimatePresence>

        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
          {children}
        </main>

        <footer className="border-t border-white/5 px-4 py-4 text-[11px] text-fg-3 sm:px-6">
          <p>
            {t("footer_line")} · <Link href="/settings" className="underline decoration-dotted">{t("nav_settings")}</Link>
          </p>
        </footer>
      </div>

      <Modal open={feedbackOpen} onClose={() => setFeedbackOpen(false)} title={t("feedback_cta")}>
        <FeedbackForm onClose={() => setFeedbackOpen(false)} />
      </Modal>
    </div>
  );
}

function FeedbackForm({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    try {
      await api.feedback({ rating, comment, tool: "app" });
      setSent(true);
      setTimeout(onClose, 1200);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (sent) {
    return <p className="text-sm text-ok">{t("feedback_thanks")}</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2" role="radiogroup" aria-label={t("feedback_rating")}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            role="radio"
            aria-checked={rating === n}
            aria-label={`${n} / 5`}
            onClick={() => setRating(n)}
            className={cn(
              "h-9 w-9 rounded-lg border text-sm transition",
              rating >= n ? "border-gold/50 bg-gold/15 text-gold" : "border-white/10 text-fg-3",
            )}
          >
            ★
          </button>
        ))}
      </div>
      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={4}
        placeholder={t("feedback_placeholder")}
        className="w-full rounded-xl border border-white/10 bg-bg-3/60 px-3 py-2 text-sm outline-none focus:border-accent/60"
      />
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          {t("cancel")}
        </Button>
        <Button onClick={submit}>{t("send")}</Button>
      </div>
    </div>
  );
}
