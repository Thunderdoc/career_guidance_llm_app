"use client";

/**
 * Small presentational primitives shared by every screen.
 *
 * Two rules from the design system live here:
 *  * `SourceLabel` — every number rendered in the UI carries its source;
 *  * `Empty` — no screen ever shows a placeholder: it either shows data or
 *    explains exactly what to do next.
 */

import { motion } from "motion/react";
import { AlertTriangle, Info, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { InView, AnimatedGroup, TextEffect } from "./motion";

export function Card({
  children,
  className,
  as: Tag = "section",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
}) {
  return (
    <Tag className={cn("rounded-2xl border border-white/8 bg-bg-2/70 p-5 backdrop-blur-sm", className)}>
      {children}
    </Tag>
  );
}

export function PageHeader({
  title,
  subtitle,
  source,
  actions,
}: {
  title: string;
  subtitle?: string;
  source?: string;
  actions?: React.ReactNode;
}) {
  return (
    <InView>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <TextEffect as="h1" className="font-serif text-3xl text-fg sm:text-4xl">
            {title}
          </TextEffect>
          {subtitle && <p className="mt-2 max-w-2xl text-sm text-fg-2">{subtitle}</p>}
          {source && <SourceLabel text={source} />}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </InView>
  );
}

export function SourceLabel({ text, className }: { text: string; className?: string }) {
  if (!text) return null;
  return (
    <p className={cn("mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed text-fg-3", className)}>
      <Info size={12} className="mt-0.5 shrink-0" aria-hidden />
      <span>{text}</span>
    </p>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-fg-3" role="status" aria-live="polite">
      <Loader2 className="animate-spin" size={16} />
      {label ?? "Loading…"}
    </div>
  );
}

export function ErrorNote({ error, retry }: { error: string; retry?: () => void }) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-xl border border-bad/30 bg-bad/10 p-3 text-sm text-fg"
    >
      <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" aria-hidden />
      <div className="flex-1">
        <p>{error}</p>
        {retry && (
          <button onClick={retry} className="mt-1 text-xs underline decoration-dotted">
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function Empty({ title, hint, action }: { title: string; hint: string; action?: React.ReactNode }) {
  return (
    <Card className="text-center">
      <p className="font-serif text-xl">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-fg-3">{hint}</p>
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </Card>
  );
}

export function Stat({
  label,
  value,
  hint,
  accent = false,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-xl border border-white/8 bg-bg-3/50 p-3">
      <div className="text-[11px] uppercase tracking-wide text-fg-3">{label}</div>
      <div className={cn("mt-1 font-serif text-2xl", accent ? "text-accent" : "text-fg")}>{value}</div>
      {hint && <div className="mt-1 text-[11px] text-fg-3">{hint}</div>}
    </div>
  );
}

export function Progress({ percent, label }: { percent: number; label?: string }) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-bg-4"
        role="progressbar"
        aria-valuenow={Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "progress"}
      >
        <motion.div
          className="h-full rounded-full bg-accent"
          initial={{ width: 0 }}
          animate={{ width: `${clamped}%` }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
    </div>
  );
}

export function Badge({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "accent" | "gold" | "ok" | "danger" }) {
  const tones = {
    muted: "bg-white/5 text-fg-2",
    accent: "bg-accent/15 text-accent",
    gold: "bg-gold/15 text-gold",
    ok: "bg-ok/15 text-ok",
    danger: "bg-danger/15 text-danger",
  } as const;
  return <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", tones[tone])}>{children}</span>;
}

export function Button({
  children,
  onClick,
  href,
  variant = "primary",
  size = "md",
  disabled,
  type = "button",
  title,
  className,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  href?: string;
  variant?: "primary" | "ghost" | "outline" | "danger";
  size?: "sm" | "md";
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
  className?: string;
}) {
  const variants = {
    primary: "bg-accent text-bg hover:brightness-110",
    ghost: "text-fg-2 hover:bg-white/5 hover:text-fg",
    outline: "border border-white/12 text-fg hover:border-accent/40 hover:text-accent",
    danger: "border border-bad/40 text-danger hover:bg-bad/10",
  } as const;
  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-2 text-sm" } as const;
  const cls = cn(
    "inline-flex items-center gap-1.5 rounded-xl font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
    variants[variant],
    sizes[size],
    className,
  );
  if (href) {
    return (
      <a href={href} className={cls} title={title}>
        {children}
      </a>
    );
  }
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title} className={cls}>
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
  htmlFor?: string;
}) {
  return (
    <label htmlFor={htmlFor} className="block">
      <span className="text-xs font-medium uppercase tracking-wide text-fg-3">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint && <span className="mt-1 block text-[11px] text-fg-3">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full rounded-xl border border-white/10 bg-bg-3/60 px-3 py-2 text-sm text-fg outline-none transition placeholder:text-fg-3 focus:border-accent/60 focus:ring-2 focus:ring-accent/20";

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={value === tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            "rounded-xl px-3 py-1.5 text-sm transition",
            value === tab.id ? "bg-accent/15 text-accent" : "text-fg-3 hover:bg-white/5 hover:text-fg",
          )}
        >
          {tab.label}
          {typeof tab.count === "number" && <span className="ml-1.5 text-[11px] text-fg-3">{tab.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Rows({ children }: { children: React.ReactNode }) {
  return <AnimatedGroup className="flex flex-col gap-2">{children}</AnimatedGroup>;
}
