"use client";

/**
 * `/plan` — self-rate → readiness → week-by-week roadmap.
 *
 * Ratings are 1–5 per skill; readiness is the importance-weighted sum of
 * strong/weak/missing credits; the roadmap orders gaps by prerequisite layer
 * then importance and schedules them by cumulative hours.
 */

import { motion } from "motion/react";
import { Calendar, Check, Download, RefreshCw, Route, Star } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { plan as planApi } from "@/lib/api";
import type { PlanResult, ReadinessResult } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { ProgressRing } from "./motion";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  PageHeader,
  Progress,
  SourceLabel,
  Spinner,
  Stat,
  inputCls,
} from "./ui";

export function PlanView({ initialCareerId }: { initialCareerId?: string }) {
  const { t } = useI18n();
  const [careerId, setCareerId] = useState(initialCareerId ?? "");
  const [readiness, setReadiness] = useState<ReadinessResult | null>(null);
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [ratings, setRatings] = useState<Record<string, number>>({});
  const [hours, setHours] = useState(6);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [target, setTarget] = useState<{ career_id: string; title: string } | null>(null);

  const loadCareer = useCallback(
    async (id: string) => {
      if (!id) return;
      setBusy(true);
      setError("");
      try {
        const [r, p] = await Promise.all([planApi.readiness(id), planApi.latest()]);
        setReadiness(r);
        setRatings(p.ratings ?? {});
        setPlan(p.plan && p.plan.career_id === id ? p.plan : null);
        setHours(p.plan?.hours_per_week ?? 6);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    planApi
      .target()
      .then((r) => {
        setTarget(r.target);
        const id = initialCareerId || r.target?.career_id || "";
        setCareerId(id);
        if (id) void loadCareer(id);
      })
      .catch((e) => setError((e as Error).message));
  }, [initialCareerId, loadCareer]);

  const rate = async (skill: string, value: number) => {
    if (!careerId) return;
    const next = { ...ratings, [skill]: value };
    setRatings(next);
    try {
      setReadiness(await planApi.rate(careerId, { [skill]: value }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const generate = async () => {
    if (!careerId) return;
    setBusy(true);
    try {
      setPlan((await planApi.generate(careerId, hours)).plan);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const markDone = async (itemId: string, done: boolean) => {
    if (!plan) return;
    try {
      const r = await planApi.setItemDone(plan.plan_id, itemId, done);
      setPlan(r.plan);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!careerId) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title={t("plan_title")} subtitle={t("plan_sub")} />
        <Empty
          title={t("plan_no_target_title")}
          hint={t("plan_no_target_hint")}
          action={<Button href="/careers">{t("dash_pick_target")}</Button>}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t("plan_title")}
        subtitle={readiness ? `${readiness.title} · ${t("plan_sub")}` : t("plan_sub")}
        source={readiness?.source}
        actions={
          <>
            <Button variant="outline" onClick={() => void loadCareer(careerId)} disabled={busy}>
              <RefreshCw size={15} /> {t("refresh")}
            </Button>
            <Button onClick={generate} disabled={busy}>
              <Route size={15} /> {plan ? t("plan_regenerate") : t("plan_generate")}
            </Button>
          </>
        }
      />

      {error && <ErrorNote error={error} retry={() => void loadCareer(careerId)} />}
      {busy && !readiness && <Spinner label={t("plan_loading")} />}

      {readiness && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card>
            <div className="flex items-center gap-4">
              <ProgressRing value={readiness.readiness_weighted} size={92} label={t("dash_readiness")} />
              <div className="text-sm">
                <p className="text-fg-2">{readiness.template}</p>
                <div className="mt-2 flex flex-col gap-1 text-xs">
                  <span className="text-ok">
                    {readiness.counts.strong} {t("status_strong")}
                  </span>
                  <span className="text-gold">
                    {readiness.counts.weak} {t("status_weak")}
                  </span>
                  <span className="text-danger">
                    {readiness.counts.missing} {t("status_missing")}
                  </span>
                </div>
              </div>
            </div>
            <Field label={t("plan_hours_label")} hint={t("plan_hours_hint")}>
              <input
                type="range"
                min={1}
                max={40}
                value={hours}
                onChange={(e) => setHours(Number(e.target.value))}
                className="w-full"
                aria-valuetext={`${hours} hours per week`}
              />
              <span className="text-sm text-accent">{hours} h / {t("plan_week")}</span>
            </Field>
          </Card>

          <Card className="lg:col-span-2" id="ratings">
            <h2 className="font-serif text-xl">{t("plan_rate")}</h2>
            <p className="mt-1 text-xs text-fg-3">{t("plan_rate_hint")}</p>
            <div className="mt-3 flex max-h-80 flex-col gap-2 overflow-y-auto pr-1">
              {readiness.skills.map((row) => (
                <div key={row.skill} className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-fg">{row.skill}</p>
                    <p className="text-[11px] text-fg-3">
                      {t("plan_importance")}: {(row.importance * 10).toFixed(0)}/10 ·{" "}
                      <span
                        className={
                          row.status === "strong" ? "text-ok" : row.status === "weak" ? "text-gold" : "text-danger"
                        }
                      >
                        {t(`status_${row.status}` as "status_strong")}
                      </span>
                    </p>
                  </div>
                  <div className="flex gap-0.5" role="radiogroup" aria-label={row.skill}>
                    {[1, 2, 3, 4, 5].map((value) => (
                      <button
                        key={value}
                        role="radio"
                        aria-checked={(ratings[row.skill] ?? row.rating) === value}
                        aria-label={`${row.skill}: ${value} / 5`}
                        onClick={() => rate(row.skill, value)}
                        className={`rounded p-0.5 ${(ratings[row.skill] ?? row.rating) >= value ? "text-gold" : "text-fg-3"}`}
                      >
                        <Star size={15} fill={(ratings[row.skill] ?? row.rating) >= value ? "currentColor" : "none"} />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <SourceLabel text={t("plan_rate_source")} />
          </Card>
        </div>
      )}

      {readiness && (
        <Card>
          <h2 className="font-serif text-xl">{t("plan_radar")}</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {readiness.radar.map((row) => (
              <div key={row.skill}>
                <div className="flex items-center justify-between text-xs text-fg-2">
                  <span className="truncate">{row.skill}</span>
                  <span>
                    {row.rating}/5 · {t("plan_target")} {Math.ceil(row.importance)}
                  </span>
                </div>
                <div className="mt-1">
                  <Progress percent={(row.rating / 5) * 100} label={`${row.skill} rating`} />
                </div>
              </div>
            ))}
          </div>
          <SourceLabel text={t("plan_radar_source")} />
        </Card>
      )}

      {plan ? (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-serif text-xl">{t("plan_roadmap")}</h2>
              <p className="text-xs text-fg-3">
                {plan.weeks} {t("plan_weeks")} · {plan.hours_per_week} h/{t("plan_week")} · {t("plan_eta")} {plan.eta} ·{" "}
                {plan.readiness_before}% → {plan.readiness_after}%
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button href={planApi.exportUrl(plan.plan_id, "pdf")} size="sm" variant="outline">
                <Download size={14} /> PDF
              </Button>
              <Button href={planApi.exportUrl(plan.plan_id, "md")} size="sm" variant="ghost">
                Markdown
              </Button>
              <Button href={planApi.exportUrl(plan.plan_id, "ics")} size="sm" variant="ghost">
                <Calendar size={14} /> Calendar
              </Button>
              <Button href={planApi.exportUrl(plan.plan_id, "json")} size="sm" variant="ghost">
                JSON
              </Button>
            </div>
          </div>

          <div className="mt-3">
            <Progress
              percent={plan.items.length ? (100 * plan.items.filter((i) => i.done).length) / plan.items.length : 0}
              label={t("plan_progress")}
            />
            <p className="mt-1 text-[11px] text-fg-3">
              {plan.items.filter((i) => i.done).length} / {plan.items.length} {t("plan_items_done")}
            </p>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1 text-xs">
              <span className="text-fg-3">{t("plan_missing_label")}</span>
              <span className="text-danger">{plan.missing_skills.length ? plan.missing_skills.join(", ") : "—"}</span>
            </div>
            <div className="flex flex-col gap-1 text-xs">
              <span className="text-fg-3">{t("plan_weak_label")}</span>
              <span className="text-gold">{plan.weak_skills.length ? plan.weak_skills.join(", ") : "—"}</span>
            </div>
          </div>

          <ol className="mt-5 flex flex-col gap-2">
            {plan.items.map((item, i) => (
              <motion.li
                key={item.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.02, 0.3) }}
                className={`rounded-xl border p-3 ${
                  item.done ? "border-ok/30 bg-ok/5" : "border-white/8 bg-bg-3/40"
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={item.status === "missing" ? "danger" : "gold"}>
                    {t("plan_week")} {item.week}
                  </Badge>
                  <span className="text-sm font-medium text-fg">{item.title}</span>
                  <span className="text-xs text-fg-3">
                    {item.hours} h · {t("plan_importance")} {item.importance}/10
                  </span>
                  <button
                    onClick={() => void markDone(item.id, !item.done)}
                    className={`ml-auto flex items-center gap-1 rounded-lg border px-2 py-1 text-xs ${
                      item.done ? "border-ok/40 text-ok" : "border-white/12 text-fg-3 hover:text-fg"
                    }`}
                    aria-pressed={item.done}
                  >
                    <Check size={13} /> {item.done ? t("plan_done") : t("plan_mark_done")}
                  </button>
                </div>
                {item.milestone && <p className="mt-1 text-xs text-fg-3">{item.milestone}</p>}
                {item.prerequisite_of.length > 0 && (
                  <p className="mt-1 text-[11px] text-fg-3">
                    {t("plan_prereq")}: {item.prerequisite_of.slice(0, 4).join(", ")}
                  </p>
                )}
                {item.resources.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                    {item.resources.map((r) => (
                      <a
                        key={`${r.url}-${r.title}`}
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-full border border-white/10 px-2 py-0.5 text-fg-2 hover:border-accent/40 hover:text-accent"
                      >
                        {r.provider ? `${r.provider}: ` : ""}
                        {r.title}
                        {r.free ? ` · ${t("learn_free")}` : ""}
                      </a>
                    ))}
                  </div>
                )}
              </motion.li>
            ))}
          </ol>
          <SourceLabel text={plan.source} />
        </Card>
      ) : (
        readiness && (
          <Card>
            <h2 className="font-serif text-xl">{t("plan_preview")}</h2>
            <p className="mt-1 text-sm text-fg-2">{t("plan_preview_hint")}</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              <Stat label={t("plan_gaps")} value={readiness.counts.missing + readiness.counts.weak} />
              <Stat
                label={t("plan_hours_total")}
                value={`${Math.round((readiness.counts.missing * 8 + readiness.counts.weak * 5) / hours) || 1} ${t("plan_weeks")}`}
              />
              <Stat label={t("dash_readiness")} value={`${readiness.readiness_weighted}%`} accent />
            </div>
            <Button className="mt-4" onClick={generate} disabled={busy}>
              <Route size={15} /> {t("plan_generate")}
            </Button>
          </Card>
        )
      )}

      {target && (
        <p className="text-xs text-fg-3">
          {t("plan_target_career")}:{" "}
          <Link href={`/careers/${target.career_id}`} className="text-accent hover:underline">
            {target.title}
          </Link>
        </p>
      )}
    </div>
  );
}
