"use client";

/**
 * `/careers/[id]` — one career in full: what the work is, what it pays, the
 * tools it uses, the education path, who can move into it, and the ladder.
 * The CTA hands the user to `/pathway?career=<id>` for the qualification check.
 */

import { ArrowLeft, Route, Wrench } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useApi } from "@/lib/use-api";
import { AnimatedGroup, TextEffect } from "./motion";
import { Badge, Button, Card, ErrorNote, SourceLabel, Spinner } from "./ui";

function money(value: number | null | undefined, symbol = "₹") {
  if (value === null || value === undefined) return "—";
  return `${symbol}${value.toLocaleString("en-IN")}`;
}

export function CareerDetailView({ careerId }: { careerId: string }) {
  const { t } = useI18n();
  const { data, error, loading, reload } = useApi(() => api.career(careerId), [careerId]);

  if (loading && !data) return <Spinner label={t("cd_loading")} />;
  if (error) return <ErrorNote error={error} retry={reload} />;
  if (!data) return null;

  const ladder = data.ladder;
  const rungs = [
    ...(ladder?.step_up ?? []),
    ...(ladder?.step_across ?? []),
    ...(ladder?.entry_points ?? []),
  ];

  return (
    <div className="flex flex-col gap-6">
      <Link href="/careers" className="inline-flex items-center gap-1.5 text-sm text-fg-3 hover:text-fg">
        <ArrowLeft size={14} /> {t("cd_back")}
      </Link>

      <header>
        <TextEffect as="h1" className="font-serif text-3xl sm:text-4xl">
          {data.title}
        </TextEffect>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-fg-3">
          <Badge tone="accent">{t("cr_zone_n").replace("{n}", String(data.job_zone))}</Badge>
          {data.holland_code && <Badge>{data.holland_code}</Badge>}
          <Badge>{data.family}</Badge>
          {data.remote && <Badge tone="ok">{t("cr_remote")}</Badge>}
        </div>
        {data.indian_titles && data.indian_titles.length > 0 && (
          <p className="mt-2 text-sm text-fg-2">{data.indian_titles.slice(0, 4).join(" · ")}</p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button href={`/pathway?career=${data.id}`} variant="primary">
            <Route size={15} /> {t("cd_pathway_cta")}
          </Button>
          <Button href={`/compare?ids=${data.id}`} variant="outline">
            {t("cd_compare_cta")}
          </Button>
          <Button href="/learn" variant="ghost">
            {t("cd_resources")}
          </Button>
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="font-serif text-xl">{t("cd_overview")}</h2>
          <p className="mt-2 text-sm text-fg-2">{data.description}</p>
          <h3 className="mt-4 text-sm font-medium uppercase tracking-wide text-fg-3">{t("cd_tasks")}</h3>
          <ul className="mt-2 flex flex-col gap-1.5 text-sm text-fg-2">
            {data.tasks.slice(0, 6).map((task) => (
              <li key={task.text} className="flex gap-2">
                <span className="text-accent">•</span> {task.text}
              </li>
            ))}
          </ul>
          <SourceLabel text={data.tasks[0]?.source ?? t("cr_source")} />
        </Card>

        <Card>
          <h2 className="font-serif text-xl">{t("cd_market")}</h2>
          <dl className="mt-3 flex flex-col gap-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-fg-3">p25</dt>
              <dd>{money(data.market?.salary_p25 ?? null)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-fg-3">p50</dt>
              <dd className="text-fg">{money(data.market?.salary_p50 ?? null)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-fg-3">p75</dt>
              <dd>{money(data.market?.salary_p75 ?? null)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-fg-3">{t("cr_demand")}</dt>
              <dd>{data.demand_label ?? data.market?.trend ?? "—"}</dd>
            </div>
          </dl>
          <SourceLabel text={data.market?.source ?? t("cr_source")} />
        </Card>
      </div>

      <AnimatedGroup className="grid gap-5 lg:grid-cols-2">
        <Card>
          <h2 className="font-serif text-xl">{t("cd_skills")}</h2>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {data.skills.slice(0, 14).map((skill) => (
              <Badge key={skill}>{skill}</Badge>
            ))}
          </div>
          <h3 className="mt-4 flex items-center gap-2 text-sm font-medium uppercase tracking-wide text-fg-3">
            <Wrench size={14} /> {t("cd_tools")}
          </h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {(data.technology ?? []).slice(0, 12).map((tool) => (
              <Badge key={tool} tone="muted">
                {tool}
              </Badge>
            ))}
          </div>
          <SourceLabel text={t("tech_source")} />
        </Card>

        <Card>
          <h2 className="font-serif text-xl">{t("cd_education")}</h2>
          <ul className="mt-3 flex flex-col gap-2 text-sm">
            {(data.education_path ?? []).map((step) => (
              <li key={step.level}>
                <p className="text-fg">{step.level}</p>
                <p className="text-fg-3">{step.typical}</p>
              </li>
            ))}
          </ul>
          <h3 className="mt-4 text-sm font-medium uppercase tracking-wide text-fg-3">{t("cd_related")}</h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {(data.related ?? []).slice(0, 6).map((item) => (
              <Link key={item.id} href={`/careers/${item.id}`}>
                <Badge>{item.title}</Badge>
              </Link>
            ))}
          </div>
        </Card>
      </AnimatedGroup>

      {rungs.length > 0 && (
        <section>
          <h2 className="font-serif text-2xl">{t("cd_ladder")}</h2>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {[
              { label: t("pw_ladder_up"), items: ladder?.step_up ?? [] },
              { label: t("pw_ladder_across"), items: ladder?.step_across ?? [] },
              { label: t("pw_ladder_entry"), items: ladder?.entry_points ?? [] },
            ].map((group) => (
              <Card key={group.label}>
                <h3 className="text-xs uppercase tracking-wide text-fg-3">{group.label}</h3>
                <ul className="mt-2 flex flex-col gap-2 text-sm">
                  {group.items.slice(0, 4).map((rung) => (
                    <li key={rung.id}>
                      <Link href={`/careers/${rung.id}`} className="text-fg hover:text-accent">
                        {rung.title}
                      </Link>
                      <p className="text-xs text-fg-3">
                        {rung.coverage}% · {rung.weeks_at_your_pace}w · {money(rung.salary_p50, "₹")}
                      </p>
                    </li>
                  ))}
                  {group.items.length === 0 && <li className="text-xs text-fg-3">—</li>}
                </ul>
              </Card>
            ))}
          </div>
          <SourceLabel text={ladder?.source ?? t("cr_source")} />
        </section>
      )}

      {data.transitions_in.length > 0 && (
        <Card>
          <h2 className="font-serif text-xl">{t("tr_title")}</h2>
          <ul className="mt-3 grid gap-2 text-sm md:grid-cols-2">
            {data.transitions_in.slice(0, 6).map((row) => (
              <li key={row.id} className="rounded-xl border border-white/8 p-3">
                <Link href={`/careers/${row.id}`} className="text-fg hover:text-accent">
                  {row.title}
                </Link>
                <p className="mt-1 text-xs text-fg-3">
                  {row.delta_skills?.slice(0, 3).join(", ") || row.shared_skills?.slice(0, 3).join(", ")}
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.resources.length > 0 && (
        <Card>
          <h2 className="font-serif text-xl">{t("cd_resources")}</h2>
          <ul className="mt-3 flex flex-col gap-2 text-sm">
            {data.resources.slice(0, 6).map((resource) => (
              <li key={resource.url} className="flex items-center justify-between gap-3">
                <a href={resource.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                  {resource.title}
                </a>
                <span className="text-xs text-fg-3">
                  {resource.skill} · {resource.provider}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
