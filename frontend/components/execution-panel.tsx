"use client";

import { motion } from "motion/react";
import { ChevronDown, Eye, FileText, Globe, Pencil, Search, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import { DrawnCheck, TextShimmer } from "./motion";

export type Step = {
  id: string;
  label: string;
  state: "pending" | "active" | "complete" | "error";
  icon: "search" | "globe" | "eye" | "document" | "pencil" | "sparkles";
};

const ICONS = { search: Search, globe: Globe, eye: Eye, document: FileText, pencil: Pencil, sparkles: Sparkles };

/** Manus-style "computer panel": transparent view of what the engine is doing. */
export function ExecutionPanel({ steps, onDismiss }: { steps: Step[]; onDismiss: () => void }) {
  const [open, setOpen] = useState(true);
  const [elapsed, setElapsed] = useState(0);
  const done = steps.filter((s) => s.state === "complete").length;
  const running = steps.some((s) => s.state === "active");
  const failed = steps.some((s) => s.state === "error");

  useEffect(() => {
    if (!running) return;
    const start = Date.now() - elapsed * 1000;
    const t = setInterval(() => setElapsed((Date.now() - start) / 1000), 100);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  return (
    <motion.section
      layout
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 12 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="overflow-hidden rounded-[var(--radius-lg)] bg-panel ring-1 ring-white/5"
      aria-live="polite"
    >
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-3 px-4 py-3 text-left">
        <span
          className={cn(
            "grid h-7 w-7 place-items-center rounded-full",
            failed ? "bg-danger/20 text-danger" : running ? "bg-active/20 text-active" : "bg-ok/20 text-ok",
          )}
        >
          {failed ? <X size={14} /> : running ? <span className="h-2.5 w-2.5 rounded-full bg-active status-pulse" /> : <DrawnCheck size={16} />}
        </span>
        <span className="flex-1 text-sm">
          {running ? <TextShimmer>{steps.find((s) => s.state === "active")?.label ?? "Working…"}</TextShimmer> : failed ? "Something went wrong" : "Analysis complete"}
        </span>
        <span className="mono text-[11px] text-fg-3">
          {elapsed.toFixed(1)}s · {done}/{steps.length}
        </span>
        <ChevronDown size={16} className={cn("text-fg-3 transition-transform", open && "rotate-180")} />
      </button>

      <motion.div initial={false} animate={{ height: open ? "auto" : 0 }} transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }} className="overflow-hidden">
        <ol className="space-y-1 border-t border-white/5 px-4 py-3">
          {steps.map((s, i) => {
            const Icon = ICONS[s.icon];
            return (
              <motion.li
                key={s.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className={cn("flex items-center gap-3 rounded-[var(--radius-sm)] px-2 py-1.5 text-sm", s.state === "pending" && "text-fg-3", s.state === "active" && "bg-bg-3 text-fg", s.state === "complete" && "text-fg-2", s.state === "error" && "text-danger")}
              >
                <span className="grid h-5 w-5 place-items-center">
                  {s.state === "complete" ? (
                    <DrawnCheck size={16} className="text-ok" />
                  ) : s.state === "active" ? (
                    <span className="h-4 w-4 rounded-full border-2 border-active/30 border-t-active loading-ring" />
                  ) : s.state === "error" ? (
                    <X size={14} />
                  ) : (
                    <span className="h-2 w-2 rounded-full border border-pending" />
                  )}
                </span>
                <Icon size={14} className="shrink-0 opacity-70" />
                <span className="flex-1">{s.label}</span>
              </motion.li>
            );
          })}
        </ol>
        {!running && (
          <div className="flex justify-end border-t border-white/5 px-4 py-2">
            <button onClick={onDismiss} className="text-xs text-fg-3 hover:text-fg">
              Dismiss
            </button>
          </div>
        )}
      </motion.div>
    </motion.section>
  );
}
