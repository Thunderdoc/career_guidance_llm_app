"use client";

/**
 * `/transitions` — “how do I get from where I am to that job?”
 * The engine walks the O*NET `related` graph breadth-first (max 3 hops) and
 * returns the missing skills for each step.
 */

import { useState } from "react";
import { ArrowRight, GitBranch } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { TransitionResult } from "@/lib/types";
import { AnimatedGroup, TextEffect } from "./motion";
import { Badge, Button, Card, Empty, ErrorNote, Spinner } from "./ui";
import { CareerPicker } from "./career-picker";

export function TransitionsView() {
  const { t } = useI18n();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [data, setData] = useState<TransitionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!from || !to) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api.transitions(from, to));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header>
        <TextEffect as="h1" className="font-serif text-3xl sm:text-4xl">
          {t("tr_title")}
        </TextEffect>
        <p className="mt-1 max-w-3xl text-sm text-fg-2">{t("tr_sub")}</p>
      </header>

      <Card className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <div>
          <label className="mb-1.5 block text-xs uppercase tracking-wide text-fg-3">{t("tr_from")}</label>
          <CareerPicker value={from} onChange={setFrom} placeholder={t("tr_from_ph")} />
        </div>
        <div>
          <label className="mb-1.5 block text-xs uppercase tracking-wide text-fg-3">{t("tr_to")}</label>
          <CareerPicker value={to} onChange={setTo} placeholder={t("tr_to_ph")} />
        </div>
        <Button variant="primary" onClick={() => void run()} disabled={!from || !to || loading}>
          <GitBranch size={15} /> {t("tr_run")}
        </Button>
      </Card>

      {loading && <Spinner label={t("tr_running")} />}
      {error && <ErrorNote error={error} />}

      {data && !loading && !data.found && <Empty title={t("tr_none")} hint={t("tr_sub")} />}

      {data && !loading && data.found && (
        <AnimatedGroup className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone="accent">{t("tr_hops").replace("{n}", String(data.hops))}</Badge>
            <Link href={`/careers/${data.from.id}`} className="text-fg hover:text-accent">
              {data.from.title}
            </Link>
            <ArrowRight size={14} className="text-fg-3" />
            <Link href={`/careers/${data.to.id}`} className="text-fg hover:text-accent">
              {data.to.title}
            </Link>
          </div>
          {data.steps.map((step, index) => (
            <Card key={`${step.id}-${index}`} className="flex gap-4">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent/15 text-sm text-accent">
                {index + 1}
              </span>
              <div>
                <Link href={`/careers/${step.id}`} className="font-medium text-fg hover:text-accent">
                  {step.title}
                </Link>
                <p className="text-xs text-fg-3">
                  {t("cr_zone_n").replace("{n}", String(step.job_zone))}
                </p>
                {step.delta_skills.length > 0 && (
                  <div className="mt-2">
                    <p className="text-xs uppercase tracking-wide text-fg-3">{t("tr_delta")}</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {step.delta_skills.slice(0, 8).map((skill) => (
                        <Badge key={skill}>{skill}</Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </Card>
          ))}
          <Card>
            <h2 className="font-serif text-xl">{t("tr_full_delta")}</h2>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {data.delta_skills.slice(0, 16).map((skill) => (
                <Badge key={skill} tone="gold">
                  {skill}
                </Badge>
              ))}
            </div>
            <p className="mt-2 text-xs text-fg-3">{data.source}</p>
            <div className="mt-3 flex gap-2">
              <Button href={`/pathway?career=${data.to.id}`} variant="primary">
                {t("cd_pathway_cta")}
              </Button>
              <Button href={`/plan`} variant="outline">
                {t("nav_plan")}
              </Button>
            </div>
          </Card>
        </AnimatedGroup>
      )}
    </div>
  );
}
