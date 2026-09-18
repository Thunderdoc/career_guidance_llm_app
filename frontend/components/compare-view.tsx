"use client";

/**
 * `/compare?ids=a,b,c` — side-by-side comparison of 2–4 careers.
 * Shared skills, the skills only one role needs, and a sourced comparison table.
 */

import { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useApi } from "@/lib/use-api";
import type { CompareResult } from "@/lib/types";
import { AnimatedGroup, TextEffect } from "./motion";
import { Badge, Button, Card, Empty, ErrorNote, Spinner } from "./ui";
import { CareerPicker } from "./career-picker";

export function CompareView({ initial = [] }: { initial?: string[] }) {
  const { t } = useI18n();
  const [ids, setIds] = useState<string[]>(initial);
  const [data, setData] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const suggestions = useApi(() => api.careers({ limit: 6 }), []);

  // Read `?ids=a,b` from the address bar (static export cannot use
  // useSearchParams without a Suspense boundary, and this keeps the shell
  // server-rendered like every other route).
  useEffect(() => {
    if (ids.length > 0) return;
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("ids");
    if (!raw) return;
    const parsed = raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, 4);
    if (parsed.length > 0) setIds(parsed);
  }, [ids.length]);

  useEffect(() => {
    if (ids.length < 2) {
      setData(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    api
      .compare(ids)
      .then((payload) => {
        if (active) setData(payload);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [ids]);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <TextEffect as="h1" className="font-serif text-3xl sm:text-4xl">
          {t("cmp_title")}
        </TextEffect>
        <p className="mt-1 text-sm text-fg-2">{t("cmp_sub")}</p>
      </header>

      <Card className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {ids.map((id) => (
            <span key={id} className="flex items-center gap-2 rounded-full border border-white/10 px-3 py-1.5 text-sm">
              {data?.careers.find((career) => career.id === id)?.title ?? id}
              <button
                type="button"
                aria-label={t("cmp_remove")}
                onClick={() => setIds(ids.filter((item) => item !== id))}
                className="text-fg-3 hover:text-danger"
              >
                <X size={13} />
              </button>
            </span>
          ))}
          {ids.length < 4 && (
            <div className="min-w-[220px] flex-1">
              <CareerPicker
                value=""
                placeholder={t("cmp_add")}
                onChange={(id) => id && !ids.includes(id) && setIds([...ids, id])}
              />
            </div>
          )}
        </div>
        {suggestions.data && ids.length < 2 && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-fg-3">
            <Plus size={12} /> {t("cmp_suggest")}
            {suggestions.data.results.slice(0, 4).map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => setIds([...ids, row.id])}
                className="rounded-full border border-white/10 px-2.5 py-1 transition hover:border-accent/40 hover:text-fg"
              >
                {row.title}
              </button>
            ))}
          </div>
        )}
      </Card>

      {ids.length < 2 && <Empty title={t("cmp_need_two")} hint={t("cmp_sub")} />}
      {loading && <Spinner label={t("cmp_loading")} />}
      {error && <ErrorNote error={error} />}

      {data && !loading && (
        <>
          <AnimatedGroup className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {data.careers.map((career) => (
              <Card key={career.id}>
                <Link href={`/careers/${career.id}`} className="font-medium text-fg hover:text-accent">
                  {career.title}
                </Link>
                <dl className="mt-3 flex flex-col gap-1.5 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-fg-3">{t("cr_zone")}</dt>
                    <dd>{career.job_zone}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-fg-3">{t("cr_salary")}</dt>
                    <dd>
                      {career.market?.salary_p50 ? `₹${career.market.salary_p50.toLocaleString("en-IN")}` : "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-fg-3">{t("cr_demand")}</dt>
                    <dd>{career.market?.trend ?? "—"}</dd>
                  </div>
                </dl>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {career.technology.slice(0, 5).map((tool) => (
                    <Badge key={tool}>{tool}</Badge>
                  ))}
                </div>
              </Card>
            ))}
          </AnimatedGroup>

          <Card>
            <h2 className="font-serif text-xl">{t("cmp_table")}</h2>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[520px] text-sm">
                <tbody>
                  {data.table.map((row) => (
                    <tr key={row.label} className="border-b border-white/8 last:border-0">
                      <th scope="row" className="py-2 pr-4 text-left font-normal text-fg-3">
                        {row.label}
                      </th>
                      {row.values.map((value, index) => (
                        <td key={index} className="py-2 pr-4 text-fg">
                          {String(value)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-fg-3">{t("cmp_table_source")}</p>
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <h2 className="font-serif text-xl">{t("cmp_shared")}</h2>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {data.shared_skills.map((skill) => (
                  <Badge key={skill} tone="ok">
                    {skill}
                  </Badge>
                ))}
              </div>
            </Card>
            <Card>
              <h2 className="font-serif text-xl">{t("cmp_unique")}</h2>
              <ul className="mt-3 flex flex-col gap-3 text-sm">
                {data.unique_skills.map((row) => (
                  <li key={row.id}>
                    <p className="text-fg-3">{row.title}</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {row.skills.slice(0, 6).map((skill) => (
                        <Badge key={skill}>{skill}</Badge>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
          <p className="text-xs text-fg-3">{t("cr_source")}</p>
        </>
      )}

      {data && (
        <div className="flex gap-2">
          <Button href={`/pathway?career=${data.careers[0].id}`} variant="primary">
            {t("cd_pathway_cta")}
          </Button>
          <Button href="/recommend" variant="outline">
            {t("nav_recommend")}
          </Button>
        </div>
      )}
    </div>
  );
}
