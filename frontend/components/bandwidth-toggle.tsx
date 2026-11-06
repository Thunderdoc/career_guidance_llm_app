"use client";

/**
 * Low-bandwidth toggle (Phase 8). Two shapes over the one control:
 * - ``full`` — settings card row: label, hint, and a switch;
 * - ``compact`` — header chip (landing + report headers): icon + On/Off.
 * Clicking sets an explicit manual preference, which always wins over
 * the Save-Data auto-detection (lib/bandwidth.ts precedence rule); the
 * switch's state shows the *effective* mode.
 */
import { Gauge } from "lucide-react";
import { useBandwidth } from "@/lib/bandwidth-context";
import { useI18n } from "@/lib/i18n";

export function BandwidthToggle({ variant = "full" }: { variant?: "full" | "compact" }) {
  const { t } = useI18n();
  const { lowBandwidth, setManual } = useBandwidth();
  const toggle = () => setManual(!lowBandwidth);

  if (variant === "compact") {
    return (
      <button
        type="button"
        onClick={toggle}
        aria-pressed={lowBandwidth}
        aria-label={t("p8_bw_label")}
        title={t("p8_bw_label")}
        className="flex items-center gap-1.5 rounded-xl border border-white/15 px-3 py-2 text-xs font-medium hover:bg-white/5"
      >
        <Gauge size={14} aria-hidden />
        {lowBandwidth ? t("p8_bw_on") : t("p8_bw_off")}
      </button>
    );
  }

  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="font-medium">{t("p8_bw_label")}</p>
        <p className="mt-1 text-sm text-fg-2">{t("p8_bw_hint")}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={lowBandwidth}
        aria-label={t("p8_bw_label")}
        onClick={toggle}
        className={`relative h-7 w-12 shrink-0 rounded-full transition-colors ${lowBandwidth ? "bg-[var(--cg-accent)]" : "bg-white/15"}`}
      >
        <span
          className={`absolute top-1 h-5 w-5 rounded-full bg-white transition-all ${lowBandwidth ? "left-6" : "left-1"}`}
        />
      </button>
    </div>
  );
}
