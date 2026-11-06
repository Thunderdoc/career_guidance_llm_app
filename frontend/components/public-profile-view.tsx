"use client";

/**
 * /p/[handle] (Phase 3): the public, opt-in profile.
 *
 * Renders ONLY what GET /api/v1/p/{handle} returns: display name, verified
 * skills, submitted projects and a 90-day plan progress summary. The API
 * never sends email/age/school, and answers 404 for non-opted-in users and
 * for minors — this view shows the same honest not-found state for both.
 */

import { BadgeCheck, ExternalLink } from "lucide-react";
import { verifyApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useApi } from "@/lib/use-api";
import { ProgressRing } from "./ui/progress-ring";
import { Badge, Card, Empty, Spinner } from "./ui";

export function PublicProfileView({ handle: given }: { handle: string }) {
  const { t } = useI18n();
  const handle =
    given === "_" && typeof window !== "undefined"
      ? (window.location.pathname.split("/").filter(Boolean).pop() ?? given)
      : given;
  const { data, error, loading } = useApi(() => verifyApi.publicProfile(handle), [handle]);

  if (loading && !data) return <Spinner label={handle} />;
  if (error || !data) return <Empty title={t("p3_profile_not_found")} hint={t("p3_public_sub")} />;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-10">
      <header>
        <h1 className="flex items-center gap-2 font-serif text-3xl">
          <BadgeCheck size={24} className="text-accent" /> {data.display_name}
        </h1>
        <p className="mt-1 text-sm text-fg-3">/p/{data.handle}</p>
      </header>

      <Card>
        <h2 className="font-serif text-xl">{t("p3_verified_skills")}</h2>
        {data.verified_skills.length === 0 ? (
          <p className="mt-2 text-sm text-fg-3">{t("p3_status_unverified")}</p>
        ) : (
          <ul className="mt-3 flex flex-wrap gap-2">
            {data.verified_skills.map((s) => (
              <li key={s.skill}>
                <Badge tone="ok">
                  {s.skill} · {s.method === "quiz" ? t("p3_method_quiz") : t("p3_method_project")}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {data.projects.length > 0 && (
        <Card>
          <h2 className="font-serif text-xl">{t("p3_projects")}</h2>
          <ul className="mt-3 flex flex-col gap-2 text-sm">
            {data.projects.map((p) => (
              <li key={`${p.skill}-${p.title}`} className="flex flex-wrap items-center gap-2">
                <a href={p.link} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                  {p.title} <ExternalLink size={12} className="inline" />
                </a>
                <Badge tone="muted">{p.skill}</Badge>
                {p.verified ? (
                  <Badge tone="ok">{t("p3_status_verified")}</Badge>
                ) : (
                  <Badge tone="gold">{t("p3_self_reported")}</Badge>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.plan_progress && (
        <Card>
          <h2 className="font-serif text-xl">{t("p3_plan_progress")}</h2>
          <div className="mt-3 flex items-center gap-4">
            <ProgressRing value={data.plan_progress.percent} size={72} label={t("p3_plan_progress")} />
            <p className="text-sm text-fg-2">
              {t("p3_week_tasks_done", {
                done: data.plan_progress.tasks_done,
                total: data.plan_progress.tasks_total,
              })}
              {data.plan_progress.current_week
                ? ` · ${t("p3_week_of", { week: data.plan_progress.current_week, total: data.plan_progress.total_weeks })}`
                : ""}
            </p>
          </div>
        </Card>
      )}

      <p className="text-xs text-fg-3">{data.source}</p>
    </div>
  );
}
