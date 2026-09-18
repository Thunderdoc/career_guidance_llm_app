"use client";

import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, Download, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, auth } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";
import type { HistoryRun } from "@/lib/types";
import { AnimatedGroup, AnimatedNumber, Disclosure, TextEffect } from "./motion";

type Analytics = { total_runs: number; ai_runs?: number; demo_runs?: number; top_careers?: [string, number][]; top_missing_skills?: [string, number][] };

export function HistoryView() {
  const [runs, setRuns] = useState<HistoryRun[] | null>(null);
  const [stats, setStats] = useState<Analytics | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [confirm, setConfirm] = useState(false);
  const { user, refresh } = useAuth();
  const { t } = useI18n();

  const load = () => {
    api.history().then((r) => setRuns(r.runs)).catch(() => setRuns([]));
    api.analytics().then((a) => setStats(a as Analytics)).catch(() => {});
  };
  useEffect(load, [user?.id]);

  const clear = async () => {
    await api.clearHistory();
    setConfirm(false);
    load();
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <TextEffect as="h1" className="font-serif text-4xl">
            History
          </TextEffect>
          <p className="mt-1 text-sm text-fg-2">
            {user ? `${t("signed_in_as")} ${user.email} — only your runs are shown.` : "Anonymous runs are saved on this server. Sign in to keep them across devices."}
          </p>
          {user && (
            <button
              onClick={async () => {
                if (window.confirm("Delete your account and all saved runs? This cannot be undone.")) {
                  await auth.deleteMe();
                  await refresh();
                }
              }}
              className="mt-2 text-[11px] text-fg-3 underline-offset-2 hover:text-danger hover:underline"
            >
              {t("delete_account")}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <a href="/api/v1/export/history.md" className="inline-flex items-center gap-1.5 rounded-full bg-bg-3 px-3 py-1.5 text-xs text-fg-2 hover:text-fg">
            <Download size={13} /> .md
          </a>
          <a href="/api/v1/export/history.json" className="inline-flex items-center gap-1.5 rounded-full bg-bg-3 px-3 py-1.5 text-xs text-fg-2 hover:text-fg">
            <Download size={13} /> .json
          </a>
          <AnimatePresence mode="wait" initial={false}>
            {confirm ? (
              <motion.div key="c" initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }} className="flex items-center gap-1">
                <button onClick={clear} className="rounded-full bg-danger px-3 py-1.5 text-xs font-medium text-white">
                  Confirm clear
                </button>
                <button onClick={() => setConfirm(false)} className="rounded-full px-3 py-1.5 text-xs text-fg-2 hover:text-fg">
                  Cancel
                </button>
              </motion.div>
            ) : (
              <motion.button key="b" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setConfirm(true)} className="inline-flex items-center gap-1.5 rounded-full bg-bg-3 px-3 py-1.5 text-xs text-fg-2 hover:text-danger">
                <Trash2 size={13} /> Clear
              </motion.button>
            )}
          </AnimatePresence>
        </div>
      </header>

      {stats && stats.total_runs > 0 && (
        <AnimatedGroup className="grid grid-cols-2 gap-3 sm:grid-cols-4" stagger={0.08}>
          <Stat label="Total runs" v={stats.total_runs} />
          <Stat label="AI runs" v={stats.ai_runs ?? 0} />
          <Stat label="Offline runs" v={stats.demo_runs ?? 0} />
          <div className="rounded-[var(--radius-lg)] bg-bg-3 p-4 ring-1 ring-white/5">
            <div className="text-[11px] uppercase tracking-wider text-fg-3">Top career</div>
            <div className="mt-1 truncate text-sm font-semibold">{stats.top_careers?.[0]?.[0] ?? "—"}</div>
            <div className="text-xs text-fg-3">Top gap: {stats.top_missing_skills?.[0]?.[0] ?? "—"}</div>
          </div>
        </AnimatedGroup>
      )}

      {runs === null && <p className="text-sm text-fg-3">Loading…</p>}
      {runs && runs.length === 0 && (
        <div className="rounded-[var(--radius-lg)] border border-dashed border-white/10 p-10 text-center text-sm text-fg-3">No runs yet. Head to Recommend to get started.</div>
      )}

      <div className="flex flex-col gap-2">
        {runs?.map((r) => (
          <div key={r.id} className="rounded-[var(--radius-lg)] bg-bg-3 ring-1 ring-white/5">
            <button onClick={() => setOpen(open === r.id ? null : r.id)} className="flex w-full items-center gap-3 px-4 py-3 text-left">
              <span className="mono text-xs text-fg-3">#{r.id}</span>
              <span className="flex-1 truncate text-sm">
                <span className="text-fg">{r.recommendations[0]?.title ?? "—"}</span>
                <span className="text-fg-3"> · {r.skills.slice(0, 60)}</span>
              </span>
              <span className="hidden text-xs text-fg-3 sm:inline">{r.created_at.replace("T", " ").slice(0, 16)}</span>
              <span className={cn("rounded-full px-2 py-0.5 text-[10px]", r.is_demo ? "bg-gold/15 text-gold" : "bg-active/15 text-[#8ab4ff]")}>{r.is_demo ? "offline" : "AI"}</span>
              <ChevronDown size={16} className={cn("text-fg-3 transition-transform", open === r.id && "rotate-180")} />
            </button>
            <Disclosure open={open === r.id}>
              <div className="border-t border-white/5 px-4 py-3">
                <div className="mb-2 text-xs text-fg-3">
                  {r.experience_level} {r.goals && `· Goal: ${r.goals}`}
                </div>
                <ol className="space-y-1.5">
                  {r.recommendations.map((x, i) => (
                    <li key={i} className="text-sm">
                      <span className="text-fg-3">{i + 1}.</span> <span className="font-medium">{x.title}</span> <span className="text-xs text-fg-3">— {x.matching_skills.length} have / {x.missing_skills.length} gaps</span>
                    </li>
                  ))}
                </ol>
                <div className="mt-3 flex gap-2">
                  <a href={api.exportUrl(r.id, "md")} className="text-xs text-accent hover:underline">
                    Export .md
                  </a>
                  <a href={api.exportUrl(r.id, "json")} className="text-xs text-accent hover:underline">
                    Export .json
                  </a>
                </div>
              </div>
            </Disclosure>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, v }: { label: string; v: number }) {
  return (
    <div className="rounded-[var(--radius-lg)] bg-bg-3 p-4 ring-1 ring-white/5">
      <div className="text-[11px] uppercase tracking-wider text-fg-3">{label}</div>
      <AnimatedNumber value={v} className="mt-1 block text-2xl font-semibold" />
    </div>
  );
}
