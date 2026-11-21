"use client";

/**
 * Kaam-Vaani portal presentation components (design layer, pass 2).
 *
 * Presentation only: no API calls, no state machines, no data flow.
 * The Stage 5/6 logic lives in components/jobs-view.tsx,
 * employer-view.tsx, kv-admin-view.tsx, kv-sharing-view.tsx and
 * kv-candidates-view.tsx; this file holds the shared look — status
 * badges, risk meter, section headers, callouts, empty states and
 * buttons — so every portal screen matches the pass-1 voice-flow
 * design (the app's dark system: teal + gold + Instrument Serif,
 * plus the additive KV tokens coral/sky/violet).
 *
 * All colours come from app/globals.css. Status text uses the
 * AA-safe tokens (danger #e86868 is measured 4.5:1 on bg-3) — never
 * a colour at low opacity, which is what made the old `flagged`
 * badge (text-red-500/30) unreadable.
 */
import Link from "next/link";
import {
  AlertTriangle,
  BadgeCheck,
  Check,
  Clock,
  Info,
  Minus,
  ShieldAlert,
  X,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/* Shared form + button classes. One primary style everywhere:       */
/* accent bg + BLACK text (pass-1 voice-flow CTA style). White text  */
/* on accent fails contrast; the old sharing/candidates primary used */
/* it, the employer portal used white-on-black — now they agree.     */
/* ------------------------------------------------------------------ */
export const kvInputCls =
  "mt-2 w-full rounded-xl border border-white/15 bg-transparent px-4 py-3 text-sm outline-none focus:border-accent/60";
export const kvLabelCls = "text-sm text-fg-2";
export const kvBtnPrimary =
  "flex min-h-[44px] items-center justify-center gap-2 rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-black transition hover:opacity-90 disabled:opacity-50";
export const kvBtnGhost =
  "flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-white/15 px-5 py-3 text-sm font-medium transition hover:bg-white/5 disabled:opacity-50";
export const kvBtnDanger =
  "flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-danger/40 bg-danger/10 px-5 py-3 text-sm font-medium text-danger transition hover:bg-danger/15 disabled:opacity-50";
export const kvLinkAccent = "text-sm text-accent underline decoration-dotted";

/* ------------------------------------------------------------------ */
/* Page header — the KV pages' shared header: wordmark + Kaam-Vaani  */
/* pill, with each page's own nav links on the right.                */
/* ------------------------------------------------------------------ */
export function KvHeader({ children }: { children?: React.ReactNode }) {
  return (
    <header className="flex items-center justify-between gap-3 py-6">
      <Link href="/" className="flex min-w-0 items-center gap-2">
        <span className="truncate font-serif text-xl">Career Guidance AI</span>
        <span className="shrink-0 rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-semibold text-accent ring-1 ring-accent/30">
          Kaam-Vaani
        </span>
      </Link>
      <div className="flex shrink-0 items-center gap-4">{children}</div>
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* Status badge — the ONE status pill for all KV surfaces. Full      */
/* literal class strings — Tailwind only picks up literals.          */
/* ------------------------------------------------------------------ */
type KvStatusMeta = { icon: LucideIcon; cls: string };

const STATUS_META: Record<string, KvStatusMeta> = {
  verified: { icon: BadgeCheck, cls: "bg-ok/15 text-ok ring-ok/30" },
  granted: { icon: BadgeCheck, cls: "bg-ok/15 text-ok ring-ok/30" },
  pending: { icon: Clock, cls: "bg-gold/15 text-gold ring-gold/30" },
  open: { icon: Clock, cls: "bg-gold/15 text-gold ring-gold/30" },
  rejected: { icon: X, cls: "bg-danger/15 text-danger ring-danger/30" },
  upheld: { icon: ShieldAlert, cls: "bg-danger/15 text-danger ring-danger/30" },
  flagged: { icon: ShieldAlert, cls: "bg-danger/15 text-danger ring-danger/30" },
  revoked: { icon: X, cls: "bg-danger/15 text-danger ring-danger/30" },
  dismissed: { icon: Minus, cls: "bg-white/5 text-fg-2 ring-white/10" },
  expired: { icon: Clock, cls: "bg-white/5 text-fg-2 ring-white/10" },
};

const DEFAULT_STATUS: KvStatusMeta = { icon: Minus, cls: "bg-white/5 text-fg-2 ring-white/10" };

export function KvStatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? DEFAULT_STATUS;
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1",
        meta.cls,
      )}
    >
      <Icon size={13} aria-hidden="true" />
      {status}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* "Sample data" chip — the honest label, everywhere the same.       */
/* ------------------------------------------------------------------ */
export function KvSampleChip() {
  return (
    <span className="inline-flex shrink-0 items-center rounded-full bg-white/5 px-2.5 py-0.5 text-xs text-fg-2 ring-1 ring-white/10">
      Sample data
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Risk meter — the scam-check score as a bar + band label, not a    */
/* bare number. Bands match the checker's own thresholds (70+ high,  */
/* 40+ medium).                                                      */
/* ------------------------------------------------------------------ */
export function KvRiskMeter({ score }: { score: number }) {
  const band = score >= 70 ? "high" : score >= 40 ? "medium" : "low";
  const meta = {
    high: { label: "High risk", bar: "bg-danger", text: "text-danger" },
    medium: { label: "Medium risk", bar: "bg-gold", text: "text-gold" },
    low: { label: "Low risk", bar: "bg-ok", text: "text-ok" },
  }[band];
  return (
    <div>
      <p className="flex items-center gap-2 text-sm font-medium">
        <ShieldAlert size={15} aria-hidden="true" className={meta.text} />
        <span className={meta.text}>
          Risk {score}/100 · {meta.label}
        </span>
      </p>
      <div
        className="mt-2 h-2 overflow-hidden rounded-full bg-white/10"
        role="meter"
        aria-valuenow={score}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Risk score ${score} out of 100, ${meta.label}`}
      >
        <div className={cn("h-full rounded-full", meta.bar)} style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Severity chip for a single risk flag (high/medium/low).           */
/* ------------------------------------------------------------------ */
export function KvSeverityChip({ severity }: { severity: string }) {
  const cls =
    severity === "high"
      ? "bg-danger/15 text-danger ring-danger/30"
      : severity === "medium"
        ? "bg-gold/15 text-gold ring-gold/30"
        : "bg-white/5 text-fg-2 ring-white/10";
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1", cls)}>
      {severity}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Section header — icon chip + serif title + optional count badge.  */
/* ------------------------------------------------------------------ */
export function KvSectionHeader({
  icon: Icon,
  title,
  count,
  tone = "accent",
}: {
  icon: LucideIcon;
  title: string;
  count?: number;
  tone?: "accent" | "gold" | "sky" | "coral" | "violet";
}) {
  const chip = {
    accent: "bg-accent/15 text-accent ring-accent/30",
    gold: "bg-gold/15 text-gold ring-gold/30",
    sky: "bg-kv-sky/15 text-kv-sky ring-kv-sky/30",
    coral: "bg-kv-coral/15 text-kv-coral ring-kv-coral/30",
    violet: "bg-kv-violet/15 text-kv-violet ring-kv-violet/30",
  }[tone];
  return (
    <div className="flex items-center gap-3">
      <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1", chip)}>
        <Icon size={18} aria-hidden="true" />
      </span>
      <h2 className="font-serif text-2xl">{title}</h2>
      {count !== undefined && (
        <span className="rounded-full bg-white/[0.07] px-2.5 py-0.5 text-xs font-semibold text-fg">{count}</span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Callout — tinted notice panel (info / warn / danger / ok).        */
/* ------------------------------------------------------------------ */
export function KvCallout({
  tone,
  children,
}: {
  tone: "info" | "warn" | "danger" | "ok";
  children: React.ReactNode;
}) {
  const meta = {
    info: { cls: "border-kv-sky/30 bg-kv-sky/10 text-fg", icon: Info, iconCls: "text-kv-sky" },
    warn: { cls: "border-gold/30 bg-gold/10 text-gold", icon: AlertTriangle, iconCls: "text-gold" },
    danger: { cls: "border-danger/30 bg-danger/10 text-danger", icon: AlertTriangle, iconCls: "text-danger" },
    ok: { cls: "border-ok/30 bg-ok/10 text-ok", icon: Check, iconCls: "text-ok" },
  }[tone];
  const Icon = meta.icon;
  return (
    <div className={cn("flex gap-2.5 rounded-xl border px-4 py-3 text-sm", meta.cls)}>
      <Icon size={16} aria-hidden="true" className={cn("mt-0.5 shrink-0", meta.iconCls)} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Empty state — icon + text for an empty list.                      */
/* ------------------------------------------------------------------ */
export function KvEmptyState({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl bg-panel px-4 py-8 text-center ring-1 ring-white/5">
      <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/[0.06] text-fg-3 ring-1 ring-white/10">
        <Icon size={22} aria-hidden="true" />
      </span>
      <p className="max-w-sm text-sm text-fg-2">{children}</p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Stat chip — a count + label for summary rows (admin queue,        */
/* outcomes).                                                        */
/* ------------------------------------------------------------------ */
export function KvStat({
  icon: Icon,
  value,
  label,
  tone = "muted",
}: {
  icon: LucideIcon;
  value: number | string;
  label: string;
  tone?: "muted" | "accent" | "gold" | "danger" | "ok";
}) {
  const text = {
    muted: "text-fg",
    accent: "text-accent",
    gold: "text-gold",
    danger: "text-danger",
    ok: "text-ok",
  }[tone];
  return (
    <span className="inline-flex items-center gap-2 rounded-xl bg-panel px-3 py-2 ring-1 ring-white/5">
      <Icon size={15} aria-hidden="true" className={text} />
      <span className="text-sm font-semibold text-fg">{value}</span>
      <span className="text-xs text-fg-2">{label}</span>
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Component bar — one labelled mini-bar of a candidate's fit        */
/* (skills / title / city / income). The number stays as text: the   */
/* bar is a visual read, not the only read.                          */
/* ------------------------------------------------------------------ */
export function KvComponentBar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-fg-2">{label}</span>
        <span className="text-xs font-semibold text-fg">{Math.round(pct)}%</span>
      </div>
      <div
        className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/10"
        role="meter"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label} ${Math.round(pct)} percent`}
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Field option — one selectable field in the grant panel. The       */
/* checkbox itself is unchanged; the card around it shows the        */
/* checked state (accent ring + tint) so a tap target is obvious.    */
/* ------------------------------------------------------------------ */
export function KvFieldOption({
  checked,
  onChange,
  name,
  explanation,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  name: string;
  explanation: string;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 text-sm ring-1 transition",
        checked ? "bg-accent/[0.07] ring-accent/40" : "bg-white/[0.03] ring-white/10 hover:bg-white/[0.05]",
      )}
    >
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4 shrink-0 accent-[#00d4aa]"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="font-medium">{name}</span>
        <span className="text-fg-2"> — {explanation}</span>
      </span>
    </label>
  );
}

/* ------------------------------------------------------------------ */
/* Audit dot colour for the sharing-history timeline.                */
/* ------------------------------------------------------------------ */
export function kvAuditDot(action: string): string {
  switch (action) {
    case "granted":
      return "bg-ok";
    case "revoked":
      return "bg-danger";
    case "accessed":
      return "bg-kv-sky";
    case "expired":
      return "bg-fg-3";
    default:
      return "bg-fg-3";
  }
}
