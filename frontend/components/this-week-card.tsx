"use client";

/**
 * Phase 3 — dashboard "This week" card for the 90-day plan.
 *
 * Kept in its own module and dynamically imported by the dashboard so the
 * /dashboard first-load JS stays inside the ≤245 kB budget. Fed by the
 * ``plan90`` block of GET /api/v1/me/dashboard (current week + progress),
 * with create/task-toggle actions against /api/v1/plan/90day.
 */

import { useState } from "react";
import { ArrowRight, CalendarRange } from "lucide-react";
import { plan90 as plan90Api, type Plan90Summary } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ProgressRing } from "./ui/progress-ring";
import { Button, Card, ErrorNote } from "./ui";

export function ThisWeekCard({
  plan90,
  onChanged,
}: {
  plan90: Plan90Summary | null;
  onChanged: () => Promise<void>;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function createPlan90() {
    setBusy(true);
    setError("");
    try {
      await plan90Api.create();
      await onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggleTask(taskId: string, done: boolean) {
    if (!plan90) return;
    setBusy(true);
    try {
      await plan90Api.setTaskDone(plan90.plan_id, taskId, done);
      await onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 font-serif text-xl">
          <CalendarRange size={17} className="text-accent" /> {t("p3_week_card_title")}
        </h2>
        {plan90 && (
          <span className="text-xs text-fg-3">
            {t("p3_week_of", { week: plan90.current_week?.week ?? 1, total: plan90.total_weeks })}
          </span>
        )}
      </div>
      {error && <ErrorNote error={error} />}
      {plan90?.current_week ? (
        <div className="mt-3 flex flex-wrap items-start gap-5">
          <ProgressRing value={plan90.progress.percent} size={84} label={t("p3_plan_progress")} />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-fg">{plan90.current_week.theme}</p>
            <p className="text-xs text-fg-3">
              {t("p3_week_tasks_done", {
                done: plan90.progress.tasks_done,
                total: plan90.progress.tasks_total,
              })}
              {" · "}
              {plan90.hours_per_week} h/{t("plan_week")}
            </p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {plan90.current_week.tasks.map((task) => (
                <li key={task.id} className="flex items-start gap-2 text-sm text-fg-2">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={task.done}
                    disabled={busy}
                    onChange={(e) => toggleTask(task.id, e.target.checked)}
                    aria-label={task.title}
                  />
                  <span className={task.done ? "line-through opacity-60" : ""}>
                    {task.title} ({task.hours} h) —{" "}
                    <a
                      href={task.resource.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent hover:underline"
                    >
                      {task.resource.provider}
                    </a>
                  </span>
                </li>
              ))}
            </ul>
            {plan90.current_week.verification_check && (
              <p className="mt-2 text-xs text-gold">{plan90.current_week.verification_check}</p>
            )}
            <div className="mt-3 flex gap-3 text-xs">
              <a href={plan90Api.exportUrl("md")} className="text-accent hover:underline">
                Markdown
              </a>
              <a href={plan90Api.exportUrl("ics")} className="text-accent hover:underline">
                ICS
              </a>
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-3">
          <p className="text-sm text-fg-2">{t("p3_no_plan90")}</p>
          <Button size="sm" className="mt-3" disabled={busy} onClick={createPlan90}>
            {t("p3_create_plan")} <ArrowRight size={14} />
          </Button>
        </div>
      )}
    </Card>
  );
}
