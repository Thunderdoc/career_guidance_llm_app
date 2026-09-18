"use client";

/**
 * Signed-in dashboard: the skills a user still needs across all their saved
 * runs, as a persistent checklist (stored server-side via /api/v1/me/progress).
 */
import { AnimatePresence, motion } from "motion/react";
import { Check, Flame, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { auth } from "@/lib/api";
import type { HistoryRun } from "@/lib/types";
import { cn } from "@/lib/cn";
import { AnimatedNumber, ProgressRing } from "./motion";

export function ProgressPanel({ runs }: { runs: HistoryRun[] }) {
  const [done, setDone] = useState<string[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    auth.progress().then((r) => setDone(r.done)).catch(() => setDone([]));
  }, []);

  // Skill → how many recommended careers need it (across all runs).
  const gaps = useMemo(() => {
    const c = new Map<string, number>();
    for (const r of runs) for (const rec of r.recommendations) for (const s of rec.missing_skills) {
      const k = s.trim().toLowerCase();
      if (k) c.set(k, (c.get(k) ?? 0) + 1);
    }
    return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 14);
  }, [runs]);

  const doneSet = useMemo(() => new Set(done ?? []), [done]);
  const total = gaps.length;
  const completed = gaps.filter(([s]) => doneSet.has(s)).length;
  const pct = total ? Math.round((100 * completed) / total) : 0;
  const careers = new Set(runs.flatMap((r) => r.recommendations.map((x) => x.title))).size;

  const toggle = async (skill: string) => {
    setBusy(skill);
    try {
      const r = await auth.setProgress(skill, !doneSet.has(skill));
      setDone(r.done);
    } finally {
      setBusy(null);
    }
  };

  if (runs.length === 0) return null;

  return (
    <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="rounded-2xl bg-bg-3 p-5 ring-1 ring-white/5">
      <div className="flex flex-wrap items-center gap-5">
        <ProgressRing value={pct} size={88} stroke={8} label="learned" />
        <div className="min-w-0 flex-1">
          <h2 className="font-serif text-2xl">Your learning progress</h2>
          <p className="mt-1 text-sm text-fg-2">
            <AnimatedNumber value={runs.length} /> saved runs · <AnimatedNumber value={careers} /> careers explored · {completed}/{total} priority skills ticked off
          </p>
        </div>
      </div>
      {done === null ? (
        <Loader2 className="mt-4 animate-spin text-fg-3" size={16} />
      ) : (
        <ul className="mt-4 grid gap-1.5 sm:grid-cols-2">
          <AnimatePresence initial={false}>
            {gaps.map(([skill, n], i) => {
              const isDone = doneSet.has(skill);
              return (
                <motion.li key={skill} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.03 }}>
                  <button
                    onClick={() => toggle(skill)}
                    disabled={busy === skill}
                    aria-pressed={isDone}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm ring-1 transition",
                      isDone ? "bg-ok/10 text-fg-2 ring-ok/20 line-through" : "bg-bg-4 text-fg ring-white/5 hover:ring-accent/40",
                    )}
                  >
                    <span className={cn("grid h-5 w-5 shrink-0 place-items-center rounded-md ring-1", isDone ? "bg-ok text-black ring-ok" : "ring-white/15")}>
                      {busy === skill ? <Loader2 size={12} className="animate-spin" /> : isDone && <Check size={12} />}
                    </span>
                    <span className="flex-1 truncate">{skill}</span>
                    {n > 1 && (
                      <span className="inline-flex items-center gap-0.5 text-[10px] text-gold" title={`Needed by ${n} recommended careers`}>
                        <Flame size={10} /> {n}
                      </span>
                    )}
                  </button>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ul>
      )}
    </motion.section>
  );
}
