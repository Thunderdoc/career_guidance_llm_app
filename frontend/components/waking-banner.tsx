"use client";

/**
 * Render's free tier sleeps the container after ~15 idle minutes; the first
 * request then takes 30–60 s. The API client reports that state here so users
 * see "Waking up the server…" (with automatic retry) instead of an error.
 */
import { AnimatePresence, motion } from "motion/react";
import { CloudOff, Loader2 } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { useServerState } from "@/lib/use-server-state";

export function WakingBanner({ className = "" }: { className?: string }) {
  const state = useServerState();
  const { t } = useI18n();
  return (
    <AnimatePresence>
      {(state === "waking" || state === "unreachable") && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          role="status"
          aria-live="polite"
          className={`flex items-center gap-3 rounded-xl px-4 py-3 text-xs ring-1 ${
            state === "waking" ? "bg-gold/10 text-fg ring-gold/30" : "bg-danger/10 text-red-200 ring-danger/30"
          } ${className}`}
        >
          {state === "waking" ? (
            <Loader2 size={14} className="shrink-0 animate-spin text-gold" />
          ) : (
            <CloudOff size={14} className="shrink-0 text-danger" />
          )}
          <span>{state === "waking" ? t("waking_server") : t("server_unreachable")}</span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
