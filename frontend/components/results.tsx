"use client";

import { motion } from "motion/react";
import { ArrowRight, BookOpen, Download, ExternalLink, GraduationCap, Route, TrendingDown, TrendingUp, Minus, Trophy, Zap } from "lucide-react";
import { useState } from "react";
import { api, formatMoney } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Recommendation, RecommendResponse } from "@/lib/types";
import { AnimatedGroup, AnimatedNumber, InView, MorphingDialog, MorphingDialogContent, MorphingDialogTrigger, Tilt } from "./motion";

const SUIT = {
  beginner: { label: "Beginner-friendly", cls: "bg-ok/15 text-ok" },
  intermediate: { label: "Intermediate", cls: "bg-active/15 text-[#8ab4ff]" },
  advanced: { label: "Advanced", cls: "bg-gold/15 text-gold" },
};

const ZONE = ["", "Little/no prep", "Some training", "Diploma / vocational", "Bachelor's typical", "Master's or higher"];

function coverage(r: Recommendation) {
  const t = r.matching_skills.length + r.missing_skills.length;
  return t ? Math.round((100 * r.matching_skills.length) / t) : 0;
}

export function Results({ result, detected, onRefine }: { result: RecommendResponse; detected: string[]; onRefine: (skill: string) => void }) {
  const recs = result.recommendations;
  const best = recs.reduce((a, b) => (coverage(b) > coverage(a) ? b : a), recs[0]);
  const [compare, setCompare] = useState<string[]>([]);
  const toggleCompare = (id: string) => setCompare((c) => (c.includes(id) ? c.filter((x) => x !== id) : c.length < 3 ? [...c, id] : c));
  const compared = recs.filter((r) => compare.includes(r.career_id));

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <InView>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-serif text-3xl">Your top {recs.length} career matches</h2>
            <p className="mt-1 text-xs text-fg-3">
              {result.provider}
              {result.used_fallback && " · AI unavailable, offline results shown"}
              {detected.length > 0 && ` · detected: ${detected.slice(0, 8).join(", ")}${detected.length > 8 ? "…" : ""}`}
            </p>
          </div>
          {result.run_id && (
            <div className="flex gap-2">
              <a href={api.exportUrl(result.run_id, "md")} className="inline-flex items-center gap-1.5 rounded-full bg-bg-3 px-3 py-1.5 text-xs text-fg-2 transition hover:bg-bg-4 hover:text-fg">
                <Download size={13} /> Markdown
              </a>
              <a href={api.exportUrl(result.run_id, "json")} className="inline-flex items-center gap-1.5 rounded-full bg-bg-3 px-3 py-1.5 text-xs text-fg-2 transition hover:bg-bg-4 hover:text-fg">
                <Download size={13} /> JSON
              </a>
            </div>
          )}
        </div>
      </InView>

      {/* Priority strip */}
      <AnimatedGroup className="grid gap-3 sm:grid-cols-3" stagger={0.1}>
        <Stat icon={<Trophy size={16} className="text-gold" />} label="Best skill fit" value={best.title.split(",")[0]} sub={`${coverage(best)}% coverage`} />
        <Stat icon={<Zap size={16} className="text-accent" />} label="Learn these first" value={result.priority_skills.slice(0, 3).join(" · ") || "—"} sub="Unlocks the most matches" />
        <Stat
          icon={<TrendingUp size={16} className="text-ok" />}
          label="Median salary range"
          value={`${formatMoney(Math.min(...recs.map((r) => r.market?.salary_p50 ?? Infinity)))} – ${formatMoney(Math.max(...recs.map((r) => r.market?.salary_p50 ?? 0)))}`}
          sub={recs[0].market?.source ?? ""}
        />
      </AnimatedGroup>

      {/* Cards */}
      <div className="flex flex-col gap-4">
        {recs.map((r, i) => (
          <InView key={r.career_id || i} delay={i * 0.05}>
            <Card rec={r} rank={i + 1} isBest={r === best} onRefine={onRefine} compared={compare.includes(r.career_id)} onCompare={() => toggleCompare(r.career_id)} />
          </InView>
        ))}
      </div>

      {/* Compare */}
      {compared.length >= 2 && (
        <InView>
          <section className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
            <h3 className="mb-3 text-sm font-semibold">Side by side</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wider text-fg-3">
                  <tr>
                    <th className="pb-2 pr-4 font-medium">Metric</th>
                    {compared.map((r) => (
                      <th key={r.career_id} className="pb-2 pr-4 font-medium text-fg">
                        {r.title}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="[&_td]:border-t [&_td]:border-white/5 [&_td]:py-2 [&_td]:pr-4">
                  <Row label="Skill coverage" cells={compared.map((r) => `${coverage(r)}%`)} />
                  <Row label="Median salary" cells={compared.map((r) => formatMoney(r.market?.salary_p50, r.market?.currency))} />
                  <Row label="Preparation" cells={compared.map((r) => ZONE[r.job_zone] ?? "—")} />
                  <Row label="Demand trend" cells={compared.map((r) => r.market?.trend ?? "—")} />
                  <Row label="Gaps to close" cells={compared.map((r) => String(r.missing_skills.length))} />
                  <Row label="Top gap" cells={compared.map((r) => r.missing_skills[0] ?? "—")} />
                </tbody>
              </table>
            </div>
          </section>
        </InView>
      )}

      <p className="text-center text-[11px] text-fg-3">
        Guidance, not a guarantee. Salary figures are {recs[0].market?.source?.startsWith("Estimate") ? "estimates" : "market data"} and vary by city and employer. Data: O*NET 24.1 (CC BY 4.0).
      </p>
    </div>
  );
}

function Row({ label, cells }: { label: string; cells: string[] }) {
  return (
    <tr>
      <td className="text-fg-3">{label}</td>
      {cells.map((c, i) => (
        <td key={i} className="capitalize">
          {c}
        </td>
      ))}
    </tr>
  );
}

function Stat({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub: string }) {
  return (
    <div className="rounded-[var(--radius-lg)] bg-bg-3 p-4 ring-1 ring-white/5">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-fg-3">
        {icon} {label}
      </div>
      <div className="mt-1 truncate text-[15px] font-semibold" title={value}>
        {value}
      </div>
      <div className="text-xs text-fg-3">{sub}</div>
    </div>
  );
}

function Trend({ t }: { t?: string }) {
  if (t === "up") return <TrendingUp size={13} className="text-ok" />;
  if (t === "down") return <TrendingDown size={13} className="text-danger" />;
  return <Minus size={13} className="text-fg-3" />;
}

function Card({ rec, rank, isBest, onRefine, compared, onCompare }: { rec: Recommendation; rank: number; isBest: boolean; onRefine: (s: string) => void; compared: boolean; onCompare: () => void }) {
  const cov = coverage(rec);
  const suit = SUIT[rec.suitability] ?? SUIT.beginner;
  return (
    <MorphingDialog>
      <Tilt max={3}>
        <MorphingDialogTrigger className={cn("group relative rounded-[var(--radius-lg)] bg-bg-3 p-5 ring-1 ring-white/5 transition-shadow hover:ring-white/10", isBest && "glow-accent")}>
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-bg-4 text-sm font-semibold text-fg-2">{rank}</span>
              <div>
                <h3 className="text-lg font-semibold leading-tight">{rec.title}</h3>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                  <span className={cn("rounded-full px-2 py-0.5", suit.cls)}>{suit.label}</span>
                  <span className="text-fg-3">{ZONE[rec.job_zone]}</span>
                  {rec.market && (
                    <span className="inline-flex items-center gap-1 text-fg-2">
                      <Trend t={rec.market.trend} /> {formatMoney(rec.market.salary_p25, rec.market.currency)}–{formatMoney(rec.market.salary_p75, rec.market.currency)}
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex flex-col items-end">
              <AnimatedNumber value={cov} className="text-2xl font-semibold text-accent" format={(v) => `${Math.round(v)}%`} />
              <span className="text-[10px] uppercase tracking-wider text-fg-3">skill match</span>
            </div>
          </div>

          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-bg-4">
            <motion.div className="h-full rounded-full bg-accent" initial={{ width: 0 }} whileInView={{ width: `${cov}%` }} viewport={{ once: true }} transition={{ duration: 1, ease: [0.22, 1, 0.36, 1] }} />
          </div>

          <p className="mt-3 text-sm leading-relaxed text-fg-2">{rec.match_reason}</p>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Chips title="You already have" items={rec.matching_skills} kind="have" />
            <Chips title="Skills to learn" items={rec.missing_skills} kind="gap" onClick={onRefine} />
          </div>

          <div className="mt-4 flex items-center justify-between">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onCompare();
              }}
              className={cn("rounded-full px-3 py-1 text-xs transition", compared ? "bg-accent/20 text-accent" : "bg-bg-4 text-fg-2 hover:text-fg")}
            >
              {compared ? "✓ Comparing" : "+ Compare"}
            </button>
            <span className="inline-flex items-center gap-1 text-xs text-fg-3 transition group-hover:text-accent">
              Roadmap, market & courses <ArrowRight size={13} />
            </span>
          </div>
        </MorphingDialogTrigger>
      </Tilt>

      <MorphingDialogContent title={rec.title}>
        <Detail rec={rec} onRefine={onRefine} />
      </MorphingDialogContent>
    </MorphingDialog>
  );
}

function Chips({ title, items, kind, onClick }: { title: string; items: string[]; kind: "have" | "gap"; onClick?: (s: string) => void }) {
  return (
    <div>
      <div className="mb-1.5 text-[11px] uppercase tracking-wider text-fg-3">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.length === 0 && <span className="text-xs italic text-fg-3">{kind === "have" ? "None detected yet" : "No gaps detected"}</span>}
        {items.slice(0, 8).map((s) => (
          <span
            key={s}
            onClick={(e) => {
              if (!onClick) return;
              e.stopPropagation();
              onClick(s);
            }}
            title={onClick ? "Add to your skills" : undefined}
            className={cn(
              "rounded-[var(--radius-sm)] px-2 py-0.5 text-xs",
              kind === "have" ? "bg-ok/10 text-[#8fe6a7] ring-1 ring-ok/20" : "bg-gold/10 text-[#f1c777] ring-1 ring-gold/20",
              onClick && "cursor-pointer hover:ring-gold/60",
            )}
          >
            {s}
          </span>
        ))}
        {items.length > 8 && <span className="text-xs text-fg-3">+{items.length - 8}</span>}
      </div>
    </div>
  );
}

function Detail({ rec, onRefine }: { rec: Recommendation; onRefine: (s: string) => void }) {
  const [tab, setTab] = useState<"path" | "next" | "market" | "learn">("path");
  const tabs = [
    { id: "path", label: "Learning path", icon: <Route size={14} /> },
    { id: "next", label: "Next steps", icon: <Zap size={14} /> },
    { id: "market", label: "Market", icon: <TrendingUp size={14} /> },
    { id: "learn", label: "Courses", icon: <BookOpen size={14} /> },
  ] as const;
  return (
    <div>
      <h3 className="pr-10 font-serif text-3xl">{rec.title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-fg-2">{rec.description}</p>
      {rec.transition_path.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-fg-2">
          <GraduationCap size={14} className="text-accent" /> Stepping stones:
          {rec.transition_path.map((t) => (
            <span key={t} className="rounded-full bg-bg-3 px-2 py-0.5">
              {t}
            </span>
          ))}
          <ArrowRight size={12} /> <span className="text-fg">{rec.title.split(",")[0]}</span>
        </div>
      )}

      <div className="mt-5 flex gap-1 rounded-full bg-bg-3 p-1">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} className={cn("relative flex flex-1 items-center justify-center gap-1.5 rounded-full px-3 py-1.5 text-xs transition", tab === t.id ? "text-black" : "text-fg-2 hover:text-fg")}>
            {tab === t.id && <motion.span layoutId={`tab-${rec.career_id}`} className="absolute inset-0 rounded-full bg-accent" transition={{ type: "spring", stiffness: 350, damping: 30 }} />}
            <span className="relative z-10 flex items-center gap-1.5">
              {t.icon} {t.label}
            </span>
          </button>
        ))}
      </div>

      <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="mt-4 min-h-[160px]">
        {tab === "path" && (
          <ol className="space-y-3">
            {rec.learning_path.map((s, i) => (
              <li key={i} className="flex gap-3 text-sm">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent text-xs font-semibold text-black">{i + 1}</span>
                <span className="pt-0.5 text-fg-2">{s}</span>
              </li>
            ))}
          </ol>
        )}
        {tab === "next" && (
          <ul className="space-y-2">
            {rec.next_steps.map((s, i) => (
              <li key={i} className="flex gap-2 text-sm text-fg-2">
                <Zap size={14} className="mt-0.5 shrink-0 text-gold" /> {s}
              </li>
            ))}
          </ul>
        )}
        {tab === "market" && rec.market && (
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              ["Entry (p25)", rec.market.salary_p25],
              ["Median (p50)", rec.market.salary_p50],
              ["Experienced (p75)", rec.market.salary_p75],
            ].map(([l, v]) => (
              <div key={String(l)} className="rounded-[var(--radius-md)] bg-bg-3 p-4">
                <div className="text-[11px] uppercase tracking-wider text-fg-3">{l}</div>
                <div className="mt-1 text-xl font-semibold">{formatMoney(v as number | null, rec.market!.currency)}</div>
              </div>
            ))}
            <div className="text-xs text-fg-3 sm:col-span-3">
              Trend: <span className="capitalize text-fg-2">{rec.market.trend}</span>
              {rec.market.postings_30d != null && ` · ${rec.market.postings_30d.toLocaleString()} postings / 30d`} · Source: {rec.market.source}
            </div>
          </div>
        )}
        {tab === "learn" && (
          <div className="space-y-2">
            {rec.resources.length === 0 && <p className="text-sm text-fg-3">No curated courses mapped yet for these gaps.</p>}
            {rec.resources.map((r) => (
              <a key={r.url} href={r.url} target="_blank" rel="noopener noreferrer" className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] bg-bg-3 px-4 py-3 text-sm transition hover:bg-bg-4">
                <div>
                  <div className="font-medium">{r.title}</div>
                  <div className="text-xs text-fg-3">
                    for <span className="text-fg-2">{r.skill}</span> · {r.provider} {r.free && <span className="ml-1 rounded-full bg-ok/15 px-1.5 text-[10px] text-ok">free</span>}
                  </div>
                </div>
                <ExternalLink size={14} className="shrink-0 text-fg-3" />
              </a>
            ))}
            <div className="pt-2 text-xs text-fg-3">
              Tip: click a gap chip to add it to your skills and re-run once you&apos;ve learned it.{" "}
              {rec.missing_skills[0] && (
                <button onClick={() => onRefine(rec.missing_skills[0])} className="text-accent hover:underline">
                  Add “{rec.missing_skills[0]}”
                </button>
              )}
            </div>
          </div>
        )}
      </motion.div>
      <div className="mt-5 text-[11px] text-fg-3">O*NET-SOC {rec.career_id} · match score {rec.match_score}</div>
    </div>
  );
}
