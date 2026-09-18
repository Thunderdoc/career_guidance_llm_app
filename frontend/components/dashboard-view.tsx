"use client";

/**
 * `/dashboard` — one screen that answers “where am I, what next?”:
 * readiness for the target career, the current roadmap week, streak/XP/badges,
 * recent runs and the announcement feed. Every number carries its source.
 */

import { motion } from "motion/react";
import {
  ArrowRight,
  Award,
  Download,
  Flame,
  Route,
  Sparkles,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import Link from "next/link";
import { auth } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useApi } from "@/lib/use-api";
import { AnimatedNumber, ProgressRing, TextEffect } from "./motion";
import { Badge, Button, Card, Empty, ErrorNote, Progress, SourceLabel, Spinner, Stat } from "./ui";

export function DashboardView() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useApi(() => auth.dashboard(), []);

  if (loading && !data) return <Spinner label={t("dash_loading")} />;
  if (error) return <ErrorNote error={error} retry={reload} />;
  if (!data) return null;

  const { profile, target, readiness, roadmap, xp, recent_runs: runs } = data;
  const streakDays = xp?.streak.days ?? [];
  const nextItem = roadmap?.items.find((item) => !item.done);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <TextEffect as="h1" className="font-serif text-3xl sm:text-4xl">
            {t("dash_hello")}
          </TextEffect>
          <p className="mt-1 text-sm text-fg-2">
            {profile?.persona ? `${profile.persona} · ` : ""}
            {profile?.experience_level || t("dash_no_profile")}
          </p>
          <SourceLabel text={t("dash_source")} />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button href="/recommend" variant="primary">
            <Sparkles size={15} /> {t("nav_recommend")}
          </Button>
          <Button href="/api/v1/me/report.pdf" variant="outline">
            <Download size={15} /> {t("dash_report")}
          </Button>
        </div>
      </header>

      {(!profile || !profile.onboarded) && (
        <Card className="border-accent/25 bg-accent/5">
          <p className="text-sm text-fg">{t("dash_onboarding_cta")}</p>
          <Button href="/onboarding" className="mt-3">
            {t("onb_title")} <ArrowRight size={15} />
          </Button>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="flex flex-wrap items-center gap-5">
            <ProgressRing value={readiness?.readiness_weighted ?? 0} size={104} label={t("dash_readiness")} />
            <div className="min-w-0 flex-1">
              <p className="text-xs uppercase tracking-wide text-fg-3">{t("dash_target")}</p>
              {target ? (
                <>
                  <Link href={`/careers/${target.career_id}`} className="font-serif text-2xl text-fg hover:text-accent">
                    {target.title}
                  </Link>
                  {readiness && (
                    <>
                      <p className="mt-1 text-sm text-fg-2">{readiness.template}</p>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <Badge tone="ok">{t("status_strong")} {readiness.counts.strong}</Badge>
                        <Badge tone="gold">{t("status_weak")} {readiness.counts.weak}</Badge>
                        <Badge tone="danger">{t("status_missing")} {readiness.counts.missing}</Badge>
                      </div>
                    </>
                  )}
                  <div className="mt-3 flex gap-2">
                    <Button href="/plan" size="sm" variant="outline">
                      <Route size={14} /> {t("dash_open_plan")}
                    </Button>
                    <Button href="/plan#ratings" size="sm" variant="ghost">
                      {t("plan_rate")}
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <p className="mt-1 text-sm text-fg-2">{t("dash_no_target")}</p>
                  <Button href="/careers" size="sm" variant="outline" className="mt-3">
                    <Target size={14} /> {t("dash_pick_target")}
                  </Button>
                </>
              )}
            </div>
          </div>
          {readiness && <SourceLabel text={readiness.source} />}
        </Card>

        <Card id="progress">
          <div className="flex items-center gap-2">
            <Award size={16} className="text-gold" />
            <h2 className="font-serif text-xl">{t("dash_progress_title")}</h2>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Stat label={t("dash_xp")} value={<AnimatedNumber value={xp?.xp ?? 0} />} accent />
            <Stat label={t("dash_level")} value={`${xp?.level ?? 1}`} hint={xp?.level_name} />
            <Stat label={t("dash_streak")} value={`${xp?.streak.current ?? 0} d`} hint={`${t("dash_longest")} ${xp?.streak.longest ?? 0} d`} />
            <Stat label={t("dash_badges")} value={xp?.badges.length ?? 0} hint={xp?.next_badge?.name ?? t("dash_all_badges")} />
          </div>
          <div className="mt-3 flex flex-wrap gap-1" aria-label={t("dash_activity")}>
            {[...Array(28)].map((_, i) => {
              const day = new Date();
              day.setDate(day.getDate() - (27 - i));
              const iso = day.toISOString().slice(0, 10);
              const active = streakDays.includes(iso);
              return (
                <span
                  key={iso}
                  title={`${iso}${active ? " · active" : ""}`}
                  className={`h-3 w-3 rounded-[3px] ${active ? "bg-accent/70" : "bg-white/8"}`}
                />
              );
            })}
          </div>
          <SourceLabel text={t("dash_progress_source")} />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <div className="flex items-center justify-between">
            <h2 className="font-serif text-xl">{t("dash_plan_title")}</h2>
            <Link href="/plan" className="text-xs text-accent hover:underline">
              {t("dash_plan_open")}
            </Link>
          </div>
          {roadmap ? (
            <div className="mt-3 flex flex-col gap-3">
              <p className="text-sm text-fg-2">
                {roadmap.weeks} {t("plan_weeks")} · {roadmap.hours_per_week} h/{t("plan_week")} · {t("plan_eta")}{" "}
                {roadmap.eta}
              </p>
              <Progress
                percent={
                  roadmap.items.length
                    ? (100 * roadmap.items.filter((i) => i.done).length) / roadmap.items.length
                    : 0
                }
                label={t("plan_progress")}
              />
              {nextItem && (
                <div className="rounded-xl border border-accent/25 bg-accent/5 p-3">
                  <p className="text-xs uppercase tracking-wide text-fg-3">{t("dash_next_up")}</p>
                  <p className="mt-1 text-sm text-fg">
                    {t("plan_week")} {nextItem.week} · {nextItem.title}
                  </p>
                  <p className="text-xs text-fg-3">
                    {nextItem.hours} h · {nextItem.milestone}
                  </p>
                </div>
              )}
              <SourceLabel text={roadmap.source} />
            </div>
          ) : target ? (
            <div className="mt-3">
              <p className="text-sm text-fg-2">{t("dash_no_plan")}</p>
              <Button href="/plan" className="mt-3" size="sm">
                {t("plan_generate")} <ArrowRight size={14} />
              </Button>
            </div>
          ) : (
            <Empty title={t("dash_empty_plan_title")} hint={t("dash_empty_plan_hint")} />
          )}
        </Card>

        <Card>
          <h2 className="font-serif text-xl">{t("dash_recent_title")}</h2>
          {runs.length === 0 ? (
            <Empty title={t("dash_empty_runs_title")} hint={t("dash_empty_runs_hint")} />
          ) : (
            <ul className="mt-3 flex flex-col gap-2">
              {runs.map((run) => (
                <motion.li
                  key={run.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-xl border border-white/8 bg-bg-3/40 p-3"
                >
                  <div className="flex items-center justify-between text-xs text-fg-3">
                    <span>{new Date(run.created_at).toLocaleString()}</span>
                    <Badge tone={run.is_demo ? "muted" : "accent"}>{run.is_demo ? t("offline_mode") : t("ai_mode")}</Badge>
                  </div>
                  <p className="mt-1 truncate text-sm text-fg">{run.skills || run.goals || "—"}</p>
                  <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-fg-3">
                    {(run.recommendations ?? []).slice(0, 3).map((rec) => (
                      <Link key={rec.career_id} href={`/careers/${rec.career_id}`} className="hover:text-accent">
                        {rec.title} · {Math.round(rec.match_percent ?? rec.match_score * 100)}%
                      </Link>
                    ))}
                  </div>
                </motion.li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex gap-2 text-xs">
            <Link href="/history" className="text-accent hover:underline">
              {t("nav_history")}
            </Link>
            <span className="text-fg-3">·</span>
            <Link href="/compare" className="text-fg-3 hover:text-accent">
              {t("nav_compare")}
            </Link>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <div className="flex items-center gap-2">
            <Flame size={16} className="text-gold" />
            <h2 className="font-serif text-xl">{t("dash_badges_title")}</h2>
          </div>
          {xp && xp.badges.length === 0 ? (
            <p className="mt-2 text-sm text-fg-3">{t("dash_badges_empty")}</p>
          ) : (
            <ul className="mt-3 flex flex-wrap gap-2">
              {xp?.badges.map((b) => (
                <li key={b.id} className="rounded-xl border border-gold/25 bg-gold/8 px-3 py-2 text-xs">
                  <p className="font-medium text-gold">{b.name}</p>
                  <p className="text-fg-3">{b.description}</p>
                </li>
              ))}
            </ul>
          )}
          <SourceLabel text={t("dash_badges_source")} />
        </Card>

        <Card>
          <h2 className="font-serif text-xl">{t("dash_next_steps_title")}</h2>
          <ul className="mt-3 flex flex-col gap-2 text-sm">
            <li className="flex items-center gap-2 text-fg-2">
              <TrendingUp size={15} className="text-accent" />
              <Link href="/discover" className="hover:text-accent">
                {t("dash_step_discover")}
              </Link>
            </li>
            <li className="flex items-center gap-2 text-fg-2">
              <Users size={15} className="text-accent" />
              <Link href="/interview" className="hover:text-accent">
                {t("dash_step_interview")}
              </Link>
            </li>
            <li className="flex items-center gap-2 text-fg-2">
              <Target size={15} className="text-accent" />
              <Link href="/jobfit" className="hover:text-accent">
                {t("dash_step_jobfit")}
              </Link>
            </li>
          </ul>
        </Card>

        <Card>
          <h2 className="font-serif text-xl">{t("dash_announcements")}</h2>
          {(data.announcements ?? []).length === 0 ? (
            <p className="mt-2 text-sm text-fg-3">{t("dash_no_announcements")}</p>
          ) : (
            <ul className="mt-3 flex flex-col gap-2 text-sm">
              {(data.announcements ?? []).map((a) => (
                <li key={a.id} className="rounded-xl border border-white/8 p-3">
                  <p className="text-fg">{a.title}</p>
                  <p className="text-xs text-fg-3">{a.body}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
