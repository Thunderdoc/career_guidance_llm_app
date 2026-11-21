"use client";

/**
 * Kaam-Vaani voice-flow presentation components (design layer).
 *
 * Presentation only: no API calls, no state machines, no data flow.
 * The voice flow's logic lives in components/voice-view.tsx; this file
 * holds the look — journey progress, waveform, match meter, category
 * icons and hero art. All colours come from the app's dark system in
 * app/globals.css (accent teal + gold) plus the additive KV tokens
 * (coral, sky, violet) — no new design language.
 */
import {
  Briefcase,
  Check,
  GraduationCap,
  HeartPulse,
  MapPin,
  Monitor,
  Scissors,
  Sprout,
  Store,
  Target,
  Truck,
  Wallet,
  Wrench,
  BookOpen,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";
import type { QuestionId } from "@/lib/voice-profile";

/* ------------------------------------------------------------------ */
/* Per-question colour + icon (question screens).                     */
/* Full literal class strings — Tailwind only picks up literals.      */
/* ------------------------------------------------------------------ */
export const KV_QUESTION_META: Record<
  QuestionId,
  { icon: LucideIcon; chip: string; bar: string; soft: string }
> = {
  skills: {
    icon: Wrench,
    chip: "bg-accent/15 text-accent ring-accent/30",
    bar: "bg-accent",
    soft: "bg-accent/[0.07]",
  },
  education: {
    icon: BookOpen,
    chip: "bg-kv-sky/15 text-kv-sky ring-kv-sky/30",
    bar: "bg-kv-sky",
    soft: "bg-kv-sky/[0.07]",
  },
  city: {
    icon: MapPin,
    chip: "bg-gold/15 text-gold ring-gold/30",
    bar: "bg-gold",
    soft: "bg-gold/[0.07]",
  },
  income: {
    icon: Wallet,
    chip: "bg-kv-coral/15 text-kv-coral ring-kv-coral/30",
    bar: "bg-kv-coral",
    soft: "bg-kv-coral/[0.07]",
  },
  goal: {
    icon: Target,
    chip: "bg-kv-violet/15 text-kv-violet ring-kv-violet/30",
    bar: "bg-kv-violet",
    soft: "bg-kv-violet/[0.07]",
  },
};

/* ------------------------------------------------------------------ */
/* Waveform bars — the listening indicator. Decorative only: the      */
/* "Listening…" text next to it carries the state for screen readers. */
/* ------------------------------------------------------------------ */
const WAVE_HEIGHTS = [10, 18, 28, 36, 28, 18, 10];

export function KvWaveform({
  active,
  className,
}: {
  active: boolean;
  className?: string;
}) {
  return (
    <div aria-hidden="true" className={cn("flex h-9 items-center gap-1", className)}>
      {WAVE_HEIGHTS.map((h, i) => (
        <span
          key={i}
          className={cn("w-1 rounded-full bg-current", active && "kv-wave-bar")}
          style={{
            height: h,
            animationDelay: active ? `${i * 0.09}s` : undefined,
            opacity: active ? undefined : 0.5,
            transform: active ? undefined : "scaleY(0.4)",
          }}
        />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Journey progress — the voice flow's 3 steps on one row. The shared */
/* Stepper (components/ui/stepper.tsx) wraps on 360px and stacks in   */
/* Tamil; this one never wraps: numbered nodes on a track, tiny       */
/* centred labels underneath (2 lines max).                           */
/* ------------------------------------------------------------------ */
export function KvJourney({ steps, current }: { steps: string[]; current: number }) {
  // Nodes sit at the centres of three equal columns (~15.5% / 50% / 84.5%
  // of the width), so the track runs between the outer node centres and
  // the fill is a plain % of that track.
  const progress = steps.length > 1 ? (Math.min(current, steps.length - 1) / (steps.length - 1)) * 100 : 0;
  return (
    <ol className="relative" aria-label="Progress">
      <span
        aria-hidden="true"
        className="absolute top-[18px] h-0.5 rounded-full bg-white/10"
        style={{ left: "15.5%", right: "15.5%" }}
      />
      <span
        aria-hidden="true"
        className="absolute top-[18px] h-0.5 rounded-full bg-accent transition-all"
        style={{ left: "15.5%", width: `${progress * 0.69}%` }}
      />
      <div className="relative flex items-start justify-between">
        {steps.map((label, i) => {
          const done = i < current;
          const isCurrent = i === current;
          return (
            <li
              key={label}
              className="flex w-[31%] flex-col items-center gap-1.5"
              aria-current={isCurrent ? "step" : undefined}
            >
              <span
                className={cn(
                  "flex h-9 w-9 items-center justify-center rounded-full text-xs font-semibold ring-2 ring-bg",
                  done && "bg-ok text-black",
                  isCurrent && "bg-white text-black",
                  !done && !isCurrent && "border border-white/20 bg-bg-2 text-fg-3",
                )}
              >
                {done ? <Check size={15} strokeWidth={3} /> : i + 1}
              </span>
              <span
                className={cn(
                  "text-center text-[11px] leading-tight",
                  isCurrent ? "font-medium text-fg" : "text-fg-3",
                )}
              >
                {label}
              </span>
            </li>
          );
        })}
      </div>
    </ol>
  );
}

/* ------------------------------------------------------------------ */
/* Match meter — 5 dots + a % badge. A visual read of the fit, not a  */
/* bare number: a low-literacy user can count the dots.               */
/* ------------------------------------------------------------------ */
export function KvMatchMeter({ value, label }: { value: number; label: string }) {
  const pct = Math.max(0, Math.min(100, value));
  const filled = Math.round(pct / 20);
  return (
    <div
      className="flex items-center gap-2"
      role="meter"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <span className="text-xs text-fg-2">{label}</span>
      <span aria-hidden="true" className="flex items-center gap-1">
        {[0, 1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className={cn("h-2.5 w-2.5 rounded-full", i < filled ? "bg-accent" : "bg-white/15")}
          />
        ))}
      </span>
      <span className="rounded-full bg-white/[0.07] px-2 py-0.5 text-xs font-semibold text-fg">
        {Math.round(pct)}%
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Category icon for a match card, from the occupation title.         */
/* Presentational keyword map — it never changes what is matched.     */
/* ------------------------------------------------------------------ */
export type KvCategory = { icon: LucideIcon; chip: string; bar: string };

const CATEGORY_RULES: { test: RegExp; category: KvCategory }[] = [
  {
    test: /teacher|instructor|educator|tutor|professor/i,
    category: { icon: GraduationCap, chip: "bg-kv-sky/15 text-kv-sky ring-kv-sky/30", bar: "bg-kv-sky" },
  },
  {
    test: /data|computer|programmer|software|operator|keyers|entry|analyst|developer/i,
    category: { icon: Monitor, chip: "bg-accent/15 text-accent ring-accent/30", bar: "bg-accent" },
  },
  {
    test: /agricultur|farm|crop|harvest|horticultur/i,
    category: { icon: Sprout, chip: "bg-ok/15 text-ok ring-ok/30", bar: "bg-ok" },
  },
  {
    test: /health|nurse|medical|care|therapist|pharma|clinic/i,
    category: { icon: HeartPulse, chip: "bg-kv-coral/15 text-kv-coral ring-kv-coral/30", bar: "bg-kv-coral" },
  },
  {
    test: /mechanic|electrician|technician|installer|repair|maintenance|welder|plumber|carpenter/i,
    category: { icon: Wrench, chip: "bg-gold/15 text-gold ring-gold/30", bar: "bg-gold" },
  },
  {
    test: /driver|delivery|truck|logistics|transport/i,
    category: { icon: Truck, chip: "bg-kv-violet/15 text-kv-violet ring-kv-violet/30", bar: "bg-kv-violet" },
  },
  {
    test: /retail|sales|shop|store|cashier|merchant/i,
    category: { icon: Store, chip: "bg-gold/15 text-gold ring-gold/30", bar: "bg-gold" },
  },
  {
    test: /tailor|garment|sewing|textile|weaver|stitch/i,
    category: { icon: Scissors, chip: "bg-kv-coral/15 text-kv-coral ring-kv-coral/30", bar: "bg-kv-coral" },
  },
];

const DEFAULT_CATEGORY: KvCategory = {
  icon: Briefcase,
  chip: "bg-accent/15 text-accent ring-accent/30",
  bar: "bg-accent",
};

export function kvCategoryForTitle(title: string): KvCategory {
  for (const rule of CATEGORY_RULES) {
    if (rule.test.test(title)) return rule.category;
  }
  return DEFAULT_CATEGORY;
}

/* ------------------------------------------------------------------ */
/* Hero sound art — concentric voice arcs for the greet panel. Pure   */
/* decoration: aria-hidden and data-decorative so low-bandwidth mode  */
/* removes it entirely.                                               */
/* ------------------------------------------------------------------ */
export function KvSoundArt({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      data-decorative="true"
      viewBox="0 0 320 120"
      fill="none"
      className={className}
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <linearGradient id="kv-sound-grad" x1="0" y1="0" x2="320" y2="0" gradientUnits="userSpaceOnUse">
          <stop stopColor="#00d4aa" />
          <stop offset="0.5" stopColor="#e6a82c" />
          <stop offset="1" stopColor="#ff8a66" />
        </linearGradient>
      </defs>
      <g stroke="url(#kv-sound-grad)" strokeLinecap="round">
        <path d="M40 100 A 90 90 0 0 1 40 20" strokeWidth="3" opacity="0.9" />
        <path d="M70 100 A 60 60 0 0 1 70 20" strokeWidth="3" opacity="0.65" />
        <path d="M100 100 A 30 30 0 0 1 100 20" strokeWidth="3" opacity="0.4" />
        <path d="M280 100 A 90 90 0 0 0 280 20" strokeWidth="3" opacity="0.9" />
        <path d="M250 100 A 60 60 0 0 0 250 20" strokeWidth="3" opacity="0.65" />
        <path d="M220 100 A 30 30 0 0 0 220 20" strokeWidth="3" opacity="0.4" />
      </g>
      <g fill="url(#kv-sound-grad)">
        <circle cx="160" cy="60" r="5" />
        <circle cx="132" cy="60" r="3.5" opacity="0.7" />
        <circle cx="188" cy="60" r="3.5" opacity="0.7" />
        <circle cx="112" cy="60" r="2.5" opacity="0.45" />
        <circle cx="208" cy="60" r="2.5" opacity="0.45" />
      </g>
    </svg>
  );
}
